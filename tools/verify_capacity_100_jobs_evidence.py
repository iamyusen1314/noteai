#!/usr/bin/env python3
"""Offline semantic verifier for Item 29 capacity evidence.

All terminal file roots and the versioned Item 28 dependency are intentionally
empty in this source-only checkpoint.  Shape-correct local JSON therefore
cannot grant readiness credit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import types
from typing import Any

from build_item29_capacity_100_evidence_v1 import (
    BUILDER_REF,
    CAPTURE_CONTRACT,
    CAPTURE_FILES,
    EXECUTOR_REF,
    PROVIDER_REQUEST_FILES,
    RAW_PROVIDER_RESPONSE_FILES,
    RECEIPT_SCHEMA,
    RENDERER_REF,
    terminal_acceptance_sha256,
)
from render_item29_capacity_100_request_v1 import (  # noqa: E402
    ACTION as REQUEST_ACTION,
    COMMAND_NAME,
)
from validate_item29_capacity_100_result_v1 import (
    EXPECTED_PROVIDER,
    EXPECTED_ROUTING,
    EXPECTED_RUNTIME,
    VALIDATOR_REF,
    validate_executor_result,
)
from verify_item29_external_authority_v1 import (
    VERIFIER_REF as EXTERNAL_AUTHORITY_VERIFIER_REF,
    validate_authority_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_capacity_100_jobs_evidence.py"
TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
DEPENDENCY_SCHEMA = "noteai.item29.item28-dependency.v1"
EVIDENCE_SCHEMA = "noteai.item29.capacity-100-evidence.v1"
CHECKPOINT_SCHEMA = "noteai.item29.terminal-evidence-checkpoint.v1"
ITEM28_TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
ITEM28_RECEIPT_SCHEMA = "noteai.item28.provider-readback-receipt.v1"
ITEM28_EVIDENCE_SCHEMA = "noteai.item28.internal-failure-rollback-evidence.v1"
ITEM28_CHECKPOINT_SCHEMA = "noteai.item28.terminal-evidence-checkpoint.v1"
EVIDENCE_REF = (
    "deploy/production/evidence/production-capacity-100-jobs-verified-20260814.json"
)
RECEIPT_REF = (
    "deploy/production/evidence/capacity-100-provider-receipt-20260814.json"
)
TERMINAL_CHECKPOINT_REF = (
    "deploy/production/evidence/capacity-100-terminal-checkpoint-20260814.json"
)
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF,
    RECEIPT_REF,
    TERMINAL_CHECKPOINT_REF,
    VERIFIER_REF,
    EXTERNAL_AUTHORITY_VERIFIER_REF,
    EXECUTOR_REF,
    RENDERER_REF,
    BUILDER_REF,
    VALIDATOR_REF,
    "tools/item29_readiness_adapter.py",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Filled mechanically only after Item 28 freezes.  No guessed Item 28 filename
# or digest is accepted by this versioned interface.
EXPECTED_ITEM28_DEPENDENCY = {
    "schema": DEPENDENCY_SCHEMA,
    "authority_root": "",
    "verifier_path": "",
    "verifier_sha256": "",
    "evidence_path": "",
    "evidence_sha256": "",
    "receipt_path": "",
    "receipt_sha256": "",
    "checkpoint_path": "",
    "checkpoint_sha256": "",
    "terminal_acceptance_sha256": "",
}

# Filled only by the post-execution terminal checkpoint.
EXPECTED_SOURCE_REVISION = ""
EXPECTED_EVIDENCE_FILE_SHA256 = ""
EXPECTED_EVIDENCE_SEMANTIC_SHA256 = ""
EXPECTED_RECEIPT_FILE_SHA256 = ""
EXPECTED_RECEIPT_SEMANTIC_SHA256 = ""
EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256 = ""
EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256 = ""

DEFAULT_READINESS = {
    "internal_verified_before": 28,
    "internal_verified_after": 29,
    "internal_total": 29,
    "internal_percentage_after": 100,
    "complete_public_verified_before": 28,
    "complete_public_verified_after": 29,
    "complete_public_total": 38,
    "complete_public_percentage_after": 76,
    "next_task": "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001",
    "public_launch_authorized": False,
    "real_provider_chain_verified": False,
    "capacity_100_jobs_verified": True,
}

ITEM28_READINESS = {
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
ITEM28_RECEIPT_KEYS = {
    "schema_version", "schema", "task_id", "action", "status",
    "observed_at_utc", "source_revision", "source_binding", "predecessors",
    "raw_closure", "request", "pre_dispatch", "terminal_readback", "result",
    "result_binding", "execution_boundary",
}
ITEM28_EVIDENCE_KEYS = {
    "schema_version", "schema", "task_id", "status", "source_revision",
    "predecessors", "provider_receipt", "rehearsal", "final_runtime_state",
    "mutation_counters", "cost_and_data_boundary", "readiness",
}
ITEM28_CHECKPOINT_KEYS = {
    "schema", "task_id", "status", "source_revision",
    "evidence_file_sha256", "evidence_semantic_sha256",
    "receipt_file_sha256", "receipt_semantic_sha256",
    "automatic_retry_allowed", "readiness_credit_added",
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


def _load(path: Path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, "cannot read canonical JSON"
    if type(value) is not dict or _canonical(value) != raw:
        return None, None, "JSON is not canonical"
    return value, raw, None


def _dependency_complete(value: Any) -> bool:
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

    return bool(
        type(value) is dict
        and set(value) == set(EXPECTED_ITEM28_DEPENDENCY)
        and value.get("schema") == DEPENDENCY_SCHEMA
        and safe_ref(value.get("verifier_path"), "tools/", ".py")
        and all(
            safe_ref(value.get(key), "deploy/production/evidence/", ".json")
            for key in ("evidence_path", "receipt_path", "checkpoint_path")
        )
        and all(
            _hex64(value.get(key))
            for key in (
                "authority_root", "verifier_sha256", "evidence_sha256",
                "receipt_sha256", "checkpoint_sha256",
                "terminal_acceptance_sha256",
            )
        )
    )


def _item28_authority_root(dependency: dict[str, str]) -> str:
    return _sha(_canonical({
        key: dependency[key]
        for key in sorted(dependency)
        if key != "authority_root"
    })[:-1])


def _load_dependency_json(path: Path):
    value, raw, error = _load(path)
    if error or value is None or raw is None:
        raise ValueError("canonical dependency artifact required")
    return value, raw


def _load_item28_verifier(path: Path, expected_sha256: str):
    raw = path.read_bytes()
    if _sha(raw) != expected_sha256:
        raise ValueError("Item28 verifier bytes mismatch")
    module = types.ModuleType("_noteai_frozen_item28_terminal_verifier")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def validate_item28_dependency(
    controls_by_id: Any,
    *,
    root: Path = ROOT,
):
    if not _dependency_complete(EXPECTED_ITEM28_DEPENDENCY):
        return ["Item29 versioned Item28 dependency authority is not finalized"], None
    if type(controls_by_id) is not dict:
        return ["Item29 predecessor controls invalid"], None
    control = controls_by_id.get("internal_failure_rollback")
    if type(control) is not dict or control.get("status") != "verified":
        return ["Item29 requires terminal Item28 verification"], None
    dependency = dict(EXPECTED_ITEM28_DEPENDENCY)
    bindings = (
        ("verifier_path", "verifier_sha256"),
        ("evidence_path", "evidence_sha256"),
        ("receipt_path", "receipt_sha256"),
        ("checkpoint_path", "checkpoint_sha256"),
    )
    for path_key, digest_key in bindings:
        try:
            observed_sha = _sha((root / dependency[path_key]).read_bytes())
        except OSError:
            return ["Item29 Item28 dependency authority file missing"], None
        if observed_sha != dependency[digest_key]:
            return ["Item29 Item28 dependency authority file mismatch"], None
    if dependency["authority_root"] != _item28_authority_root(dependency):
        return ["Item29 Item28 dependency authority root mismatch"], None
    refs = {
        row.get("ref") for row in control.get("evidence", [])
        if type(row) is dict and set(row) == {"kind", "ref"}
        and row.get("kind") == "path"
    }
    if any(dependency[path_key] not in refs for path_key, _digest_key in bindings):
        return ["Item29 Item28 dependency authority ref missing"], None
    try:
        item28_verifier = _load_item28_verifier(
            root / dependency["verifier_path"], dependency["verifier_sha256"]
        )
        receipt, receipt_raw = _load_dependency_json(
            root / dependency["receipt_path"]
        )
        evidence, evidence_raw = _load_dependency_json(
            root / dependency["evidence_path"]
        )
        checkpoint, _checkpoint_raw = _load_dependency_json(
            root / dependency["checkpoint_path"]
        )
    except Exception as exc:
        return ["Item29 Item28 dependency verifier/artifact invalid: " + str(exc)], None

    expected_module_identity = {
        "VERIFIER_REF": dependency["verifier_path"],
        "TASK_ID": ITEM28_TASK_ID,
        "RECEIPT_SCHEMA": ITEM28_RECEIPT_SCHEMA,
        "EVIDENCE_SCHEMA": ITEM28_EVIDENCE_SCHEMA,
        "CHECKPOINT_SCHEMA": ITEM28_CHECKPOINT_SCHEMA,
        "EVIDENCE_REF": dependency["evidence_path"],
        "RECEIPT_REF": dependency["receipt_path"],
        "TERMINAL_CHECKPOINT_REF": dependency["checkpoint_path"],
        "EXPECTED_EVIDENCE_FILE_SHA256": dependency["evidence_sha256"],
        "EXPECTED_RECEIPT_FILE_SHA256": dependency["receipt_sha256"],
        "EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256": dependency[
            "checkpoint_sha256"
        ],
    }
    if any(
        getattr(item28_verifier, key, None) != expected
        for key, expected in expected_module_identity.items()
    ) or not _strict(
        getattr(item28_verifier, "DEFAULT_READINESS", None), ITEM28_READINESS
    ):
        return ["Item29 frozen Item28 verifier identity mismatch"], None
    required_calls = (
        "validate_predecessor_evidence", "validate_manifest_evidence",
        "validate_receipt", "validate_evidence",
    )
    if any(not callable(getattr(item28_verifier, name, None)) for name in required_calls):
        return ["Item29 frozen Item28 verifier interface mismatch"], None
    source_revision = receipt.get("source_revision")
    if (
        type(receipt) is not dict
        or set(receipt) != ITEM28_RECEIPT_KEYS
        or receipt.get("schema") != ITEM28_RECEIPT_SCHEMA
        or receipt.get("task_id") != ITEM28_TASK_ID
        or receipt.get("status") != "PROVIDER_TERMINAL_VERIFIED"
        or type(source_revision) is not str
        or HEX40.fullmatch(source_revision) is None
        or getattr(item28_verifier, "EXPECTED_SOURCE_REVISION", None)
        != source_revision
    ):
        return ["Item29 strict Item28 receipt schema mismatch"], None
    if (
        type(evidence) is not dict
        or set(evidence) != ITEM28_EVIDENCE_KEYS
        or evidence.get("schema") != ITEM28_EVIDENCE_SCHEMA
        or evidence.get("task_id") != ITEM28_TASK_ID
        or evidence.get("status") != "PASS"
        or evidence.get("source_revision") != source_revision
    ):
        return ["Item29 strict Item28 evidence schema mismatch"], None
    if (
        type(checkpoint) is not dict
        or set(checkpoint) != ITEM28_CHECKPOINT_KEYS
        or checkpoint.get("schema") != ITEM28_CHECKPOINT_SCHEMA
        or checkpoint.get("task_id") != ITEM28_TASK_ID
        or checkpoint.get("status") != "EXACT_HEAD_CI_ACCEPTED"
        or checkpoint.get("source_revision") != source_revision
    ):
        return ["Item29 strict Item28 checkpoint schema mismatch"], None
    try:
        predecessor_errors, predecessors = (
            item28_verifier.validate_predecessor_evidence(
                controls_by_id, root=root
            )
        )
        if predecessor_errors or type(predecessors) is not dict:
            return [
                "Item29 frozen Item28 predecessor verifier rejected: "
                + (predecessor_errors[0] if predecessor_errors else "missing")
            ], None
        manifest_errors = item28_verifier.validate_manifest_evidence(
            control.get("evidence"), root=root,
            expected_predecessors=predecessors,
            expected_readiness=ITEM28_READINESS,
        )
        if manifest_errors:
            return [
                "Item29 frozen Item28 manifest verifier rejected: "
                + manifest_errors[0]
            ], None
        receipt_errors, acceptance = item28_verifier.validate_receipt(
            receipt, expected_predecessors=predecessors, root=root,
        )
        if receipt_errors or acceptance != dependency["terminal_acceptance_sha256"]:
            return [
                "Item29 frozen Item28 receipt verifier rejected: "
                + (receipt_errors[0] if receipt_errors else "acceptance mismatch")
            ], None
        evidence_errors = item28_verifier.validate_evidence(
            evidence, receipt, expected_predecessors=predecessors,
            expected_readiness=ITEM28_READINESS, root=root,
        )
        if evidence_errors:
            return [
                "Item29 frozen Item28 evidence verifier rejected: "
                + evidence_errors[0]
            ], None
    except Exception as exc:
        return ["Item29 frozen Item28 verifier call failed: " + str(exc)], None
    return [], dependency


def validate_receipt(
    value: Any,
    *,
    expected_item28_dependency: dict[str, str],
    root: Path = ROOT,
):
    errors: list[str] = []
    keys = {
        "schema_version", "schema", "task_id", "action", "status",
        "observed_at_utc", "source_revision", "source_binding",
        "item28_dependency", "raw_closure", "request", "pre_dispatch",
        "terminal_readback", "result", "result_binding",
        "execution_boundary", "terminal_acceptance_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        return ["Item29 receipt schema mismatch"], None
    if (
        not _strict(value.get("schema_version"), 1)
        or value.get("schema") != RECEIPT_SCHEMA
        or value.get("task_id") != TASK_ID
        or value.get("action") != REQUEST_ACTION
        or value.get("status") != "PROVIDER_TERMINAL_VERIFIED"
        or value.get("source_revision") != EXPECTED_SOURCE_REVISION
        or type(value.get("observed_at_utc")) is not str
        or UTC.fullmatch(value["observed_at_utc"]) is None
        or not _strict(value.get("item28_dependency"), expected_item28_dependency)
    ):
        errors.append("Item29 receipt identity/dependency mismatch")
    expected_refs = {
        "executor": EXECUTOR_REF,
        "renderer": RENDERER_REF,
        "builder": BUILDER_REF,
        "validator": VALIDATOR_REF,
    }
    source = value.get("source_binding")
    if type(source) is not dict or set(source) != set(expected_refs):
        errors.append("Item29 receipt source binding schema mismatch")
    else:
        for label, ref in expected_refs.items():
            row = source[label]
            try:
                raw = (root / ref).read_bytes()
            except OSError:
                raw = b""
            if not _strict(
                row, {"path": ref, "bytes": len(raw), "sha256": _sha(raw)}
            ):
                errors.append("Item29 receipt source binding mismatch")
                break
    raw_closure = value.get("raw_closure")
    if (
        type(raw_closure) is not dict
        or set(raw_closure) != {
            "capture_contract", "capture_file_count",
            "capture_manifest_canonical_bytes",
            "capture_manifest_sha256", "raw_provider_response_count",
            "provider_request_count", "raw_provider_bodies_retained_root_only",
            "raw_provider_value_emitted_count",
        }
        or raw_closure.get("capture_contract") != CAPTURE_CONTRACT
        or not _strict(
            raw_closure.get("capture_file_count"), len(CAPTURE_FILES)
        )
        or type(raw_closure.get("capture_manifest_canonical_bytes")) is not int
        or raw_closure["capture_manifest_canonical_bytes"] <= 0
        or not _strict(
            raw_closure.get("raw_provider_response_count"),
            len(RAW_PROVIDER_RESPONSE_FILES),
        )
        or not _strict(
            raw_closure.get("provider_request_count"),
            len(PROVIDER_REQUEST_FILES),
        )
        or not _hex64(raw_closure.get("capture_manifest_sha256"))
        or raw_closure.get("raw_provider_bodies_retained_root_only") is not True
        or not _strict(raw_closure.get("raw_provider_value_emitted_count"), 0)
    ):
        errors.append("Item29 receipt raw closure mismatch")
    request = value.get("request")
    if (
        type(request) is not dict
        or set(request) != {
            "command_name", "request_sha256",
            "client_token_commitment_sha256", "target_commitment_sha256",
            "command_id_commitment_sha256", "invoke_id_commitment_sha256",
        }
        or request.get("command_name") != COMMAND_NAME
        or any(
            not _hex64(request.get(key))
            for key in set(request) - {"command_name"}
        )
    ):
        errors.append("Item29 receipt request commitment mismatch")
    pre = value.get("pre_dispatch") or {}
    if not _strict(pre, {
        "history_key": "Name",
        "all_pages": True,
        "exact_command_name_history_count": 0,
        "exact_invocation_name_history_count": 0,
        "provider_client_token_readback_supported": False,
    }):
        errors.append("Item29 receipt pre-dispatch mismatch")
    terminal = value.get("terminal_readback") or {}
    if not _strict(terminal, {
        "all_pages": True,
        "command_match_count": 1,
        "invocation_match_count": 1,
        "result_match_count": 1,
        "provider_status": "Finished",
        "provider_result_status": "Success",
        "exit_code": 0,
        "dropped_count": 0,
        "repeat_count": 1,
    }):
        errors.append("Item29 receipt terminal readback mismatch")
    result_errors, binding = validate_executor_result(value.get("result"))
    if result_errors or binding is None or not _strict(
        value.get("result_binding"), binding
    ):
        errors.append("Item29 receipt result mismatch")
    boundary = value.get("execution_boundary") or {}
    if not _strict(boundary, {
        "dispatch_count": 1,
        "automatic_retry_count": 0,
        "same_request_resubmit_allowed": False,
        "provider_unknown": False,
        "provider_client_token_readback_supported": False,
        "provider_history_key": "Name",
        "real_provider_call_count": 0,
        "wrapper_child_exec_used": False,
        "wrapper_host_temp_file_count": 4,
        "wrapper_host_temp_residue_count": 0,
        "wrapper_temp_residue_absence_audited_before_output": True,
    }):
        errors.append("Item29 receipt execution boundary mismatch")
    acceptance = terminal_acceptance_sha256(value)
    if value.get("terminal_acceptance_sha256") != acceptance:
        errors.append("Item29 receipt terminal acceptance mismatch")
    return errors, (acceptance if not errors else None)


def validate_evidence(
    value: Any,
    receipt: Any,
    *,
    expected_item28_dependency: dict[str, str],
    expected_readiness: dict[str, Any],
    authority_binding: dict[str, Any],
):
    keys = {
        "schema_version", "schema", "task_id", "status", "source_revision",
        "item28_dependency", "provider_receipt", "external_authority",
        "capacity", "headroom", "admission", "routing_and_recovery",
        "provider", "accounting", "cleanup", "execution_boundary", "readiness",
    }
    errors: list[str] = []
    if type(value) is not dict or set(value) != keys:
        return ["Item29 evidence schema mismatch"]
    if (
        not _strict(value.get("schema_version"), 1)
        or value.get("schema") != EVIDENCE_SCHEMA
        or value.get("task_id") != TASK_ID
        or value.get("status") != "PASS"
        or value.get("source_revision") != EXPECTED_SOURCE_REVISION
        or not _strict(value.get("item28_dependency"), expected_item28_dependency)
        or not _strict(value.get("readiness"), expected_readiness)
    ):
        errors.append("Item29 evidence identity/dependency/readiness mismatch")
    acceptance = terminal_acceptance_sha256(receipt)
    if not _strict(value.get("provider_receipt"), {
        "path": RECEIPT_REF,
        "file_sha256": EXPECTED_RECEIPT_FILE_SHA256,
        "semantic_sha256": EXPECTED_RECEIPT_SEMANTIC_SHA256,
        "terminal_acceptance_sha256": acceptance,
    }):
        errors.append("Item29 evidence receipt binding mismatch")
    if not _strict(value.get("external_authority"), authority_binding):
        errors.append("Item29 evidence external authority mismatch")
    result = receipt.get("result") if type(receipt) is dict else {}
    if not _strict(value.get("capacity"), {
        "operation_count": 100,
        "succeeded_count": 100,
        "lost_operation_count": 0,
        "claim_count": 102,
        "takeover_count": 2,
    }):
        errors.append("Item29 evidence capacity mismatch")
    if not _strict(value.get("headroom"), result.get("headroom")):
        errors.append("Item29 evidence headroom mismatch")
    if not _strict(value.get("admission"), result.get("admission")):
        errors.append("Item29 evidence admission mismatch")
    if not _strict(
        value.get("routing_and_recovery"), result.get("routing_and_recovery")
    ) or not _strict(value.get("provider"), EXPECTED_PROVIDER):
        errors.append("Item29 evidence routing/provider mismatch")
    runtime = result.get("runtime_projection") or {}
    accounting = {
        key: runtime[key] for key in (
            "settlement_completed_count", "settlement_refunded_count",
            "settlement_needs_manual_count", "charge_applied_count",
            "complete_applied_count", "usage_record_count",
            "expected_credits_milli", "actual_credits_milli",
            "overcharge_credits_milli", "payment_record_delta_count",
            "cash_balance_delta_milli",
        )
    } if all(key in runtime for key in EXPECTED_RUNTIME) else {}
    cleanup = {
        key: runtime[key] for key in (
            "ready_request_object_residue_count",
            "ready_result_object_residue_count", "primary_user_residue_count",
            "admission_residue_count", "idempotency_residue_count",
            "pseudonymous_operation_audit_count",
            "pseudonymous_provider_attempt_audit_count",
            "pseudonymous_usage_audit_count",
        )
    } if all(key in runtime for key in EXPECTED_RUNTIME) else {}
    if not _strict(value.get("accounting"), accounting):
        errors.append("Item29 evidence accounting mismatch")
    if not _strict(value.get("cleanup"), cleanup):
        errors.append("Item29 evidence cleanup mismatch")
    if not _strict(value.get("execution_boundary"), result.get("execution_boundary")):
        errors.append("Item29 evidence execution boundary mismatch")
    return errors


def validate_manifest_evidence(
    entries: Any,
    *,
    root: Path = ROOT,
    expected_item28_dependency: dict[str, str],
    expected_readiness: dict[str, Any],
):
    refs = {
        row.get("ref") for row in entries or []
        if type(row) is dict and row.get("kind") == "path"
    }
    if refs != REQUIRED_MANIFEST_PATH_REFS:
        return ["Item29 exact manifest evidence refs required"]
    authorities = (
        EXPECTED_SOURCE_REVISION,
        EXPECTED_EVIDENCE_FILE_SHA256,
        EXPECTED_EVIDENCE_SEMANTIC_SHA256,
        EXPECTED_RECEIPT_FILE_SHA256,
        EXPECTED_RECEIPT_SEMANTIC_SHA256,
        EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256,
        EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256,
    )
    if (
        HEX40.fullmatch(EXPECTED_SOURCE_REVISION or "") is None
        or any(not _hex64(value) for value in authorities[1:])
    ):
        return ["Item29 terminal evidence authority is not finalized"]
    if not _strict(expected_item28_dependency, EXPECTED_ITEM28_DEPENDENCY):
        return ["Item29 Item28 dependency authority mismatch"]
    evidence, evidence_raw, error = _load(root / EVIDENCE_REF)
    receipt, receipt_raw, receipt_error = _load(root / RECEIPT_REF)
    checkpoint, checkpoint_raw, checkpoint_error = _load(
        root / TERMINAL_CHECKPOINT_REF
    )
    if error or receipt_error or checkpoint_error:
        return [error or receipt_error or checkpoint_error or "Item29 evidence read error"]
    assert evidence is not None and evidence_raw is not None
    assert receipt is not None and receipt_raw is not None
    assert checkpoint is not None and checkpoint_raw is not None
    errors: list[str] = []
    if (
        _sha(evidence_raw) != EXPECTED_EVIDENCE_FILE_SHA256
        or _semantic(evidence) != EXPECTED_EVIDENCE_SEMANTIC_SHA256
        or _sha(receipt_raw) != EXPECTED_RECEIPT_FILE_SHA256
        or _semantic(receipt) != EXPECTED_RECEIPT_SEMANTIC_SHA256
        or _sha(checkpoint_raw) != EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256
        or _semantic(checkpoint) != EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256
    ):
        errors.append("Item29 terminal file authority mismatch")
    receipt_errors, acceptance = validate_receipt(
        receipt, expected_item28_dependency=expected_item28_dependency, root=root
    )
    errors.extend(receipt_errors)
    if acceptance is None:
        return errors or ["Item29 receipt acceptance missing"]
    authority_errors, authority_binding = validate_authority_bundle(
        source_revision=EXPECTED_SOURCE_REVISION,
        receipt_sha256=EXPECTED_RECEIPT_FILE_SHA256,
        terminal_acceptance_sha256=acceptance,
    )
    errors.extend(authority_errors)
    if authority_binding is not None:
        errors.extend(validate_evidence(
            evidence,
            receipt,
            expected_item28_dependency=expected_item28_dependency,
            expected_readiness=expected_readiness,
            authority_binding=authority_binding,
        ))
    expected_checkpoint = {
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
    if not _strict(checkpoint, expected_checkpoint):
        errors.append("Item29 terminal checkpoint mismatch")
    return errors
