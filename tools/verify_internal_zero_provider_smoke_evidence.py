#!/usr/bin/env python3
"""Verify the Secret-free Item 27 private zero-provider smoke evidence.

The verifier is deliberately offline.  It accepts only the four ordered,
terminal Cloud Assistant results, revalidates every executor projection and
derives the aggregate counts from those results.  It cannot grant provider,
public-launch, failure-rehearsal, or capacity credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from build_item27_internal_smoke_evidence_v1 import (
    BUILDER_REF,
    CAPTURE_CONTRACT,
    CAPTURE_FILES,
    PROVIDER_RAW_RESPONSE_FILES,
    PROVIDER_REQUEST_FILES,
    terminal_acceptance_sha256,
)
from render_item27_internal_smoke_requests_v1 import (
    ACTIONS as REQUEST_ACTIONS,
)
from render_item27_internal_smoke_requests_v1 import (
    PREDECESSOR_ACCEPTANCE_SOURCES,
)
from render_item27_internal_smoke_requests_v1 import (
    _command_content as render_command_content,
)
from render_item27_internal_smoke_requests_v1 import (
    _read_executor as read_frozen_executor,
)
from render_item27_internal_smoke_requests_v1 import (
    _render_wrapper as render_command_wrapper,
)
from validate_item27_internal_smoke_result_v1 import (
    VALIDATOR_REF,
    validate_executor_result,
)
from verify_item27_external_authority_v1 import (
    GIT_PATH,
    REPOSITORY,
    SOURCE_REF,
    _run_trusted,
    VERIFIER_REF as AUTHORITY_VERIFIER_REF,
    validate_authority_bundle,
)
from verify_pitr_restore_evidence import (
    validate_manifest_evidence as validate_item26_terminal_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-internal-zero-provider-smoke-verified-20260813.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
RESULT_SCHEMA = "noteai.item27.internal-zero-provider-smoke.v1"
RECEIPT_SCHEMA = "noteai.item27.provider-readback-receipt.v1"
TERMINAL_CHECKPOINT_SCHEMA = "noteai.item27.terminal-evidence-checkpoint.v1"
EXECUTOR_REF = "deploy/production/internal_zero_provider_smoke.py"
RENDERER_REF = "tools/render_item27_internal_smoke_requests_v1.py"
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
ACTION_ROWS = (
    ("api_c", "api-c", 8, ("dispatcher", "payment")),
    ("api_f", "api-f", 5, ("trends", "tracking")),
    ("worker_c", "worker-c", 0, ("worker",)),
    ("worker_f", "worker-f", 0, ("worker",)),
)
ACTION_ORDER = tuple(row[0] for row in ACTION_ROWS)
RECEIPT_REFS = {
    action: (
        "deploy/production/evidence/"
        f"internal-zero-provider-smoke-{mode}-provider-receipt-20260813.json"
    )
    for action, mode, _endpoint_count, _roles in ACTION_ROWS
}
TERMINAL_CHECKPOINT_REF = (
    "deploy/production/evidence/"
    "internal-zero-provider-smoke-terminal-checkpoint-20260813.json"
)
# These trust roots are deliberately empty in the pre-execution source
# checkpoint.  The terminal evidence checkpoint must freeze every exact file
# and semantic digest after provider readback; until then the readiness gate
# cannot accept an otherwise well-shaped offline fixture.
EXPECTED_EVIDENCE_FILE_SHA256 = ""
EXPECTED_EVIDENCE_SEMANTIC_SHA256 = ""
EXPECTED_RECEIPT_FILE_SHA256 = {action: "" for action in RECEIPT_REFS}
EXPECTED_RECEIPT_SEMANTIC_SHA256 = {action: "" for action in RECEIPT_REFS}
# This second-stage trust root is filled only after the evidence checkpoint was
# pushed and its exact push/PR CI runs passed.  It intentionally cannot be
# finalized in the pre-execution source checkpoint.
EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256 = ""
EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256 = ""

REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF,
    TERMINAL_CHECKPOINT_REF,
    "tools/verify_internal_zero_provider_smoke_evidence.py",
    BUILDER_REF,
    VALIDATOR_REF,
    AUTHORITY_VERIFIER_REF,
    EXECUTOR_REF,
    RENDERER_REF,
    *RECEIPT_REFS.values(),
}
TOP_LEVEL_KEYS = {
    "schema_version",
    "task_id",
    "status",
    "observed_at_utc",
    "source_binding",
    "invocations",
    "aggregate",
    "final_runtime_state",
    "mutation_counters",
    "cost_and_data_boundary",
    "secret_free_evidence",
    "readiness",
}
COMMON_RESULT_KEYS = {
    "schema",
    "task_id",
    "status",
    "mode",
    "loopback_endpoint_count",
    "endpoint_projections",
    "roles",
    "active_runtime_identity_unchanged",
    "public_listener_count",
    "service_start_count",
    "service_stop_count",
    "original_state_restored",
    "provider_call_count",
    "provider_attempt_count",
    "oss_mutation_count",
    "production_database_mutation_count",
    "synthetic_record_count",
    "public_request_count",
    "cleanup",
    "automatic_retry_allowed",
    "same_invocation_replay_allowed",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_EVIDENCE_BYTES = 512 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
DEFAULT_READINESS = {
    "internal_verified_before": 26,
    "internal_verified_after": 27,
    "internal_total": 29,
    "internal_percentage_after": 93,
    "complete_public_verified_before": 26,
    "complete_public_verified_after": 27,
    "complete_public_total": 38,
    "complete_public_percentage_after": 71,
    "next_task": "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001",
    "public_launch_authorized": False,
    "real_provider_chain_verified": False,
    "full_system_failure_rollback_verified": False,
    "capacity_100_jobs_verified": False,
}


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _exact_dict(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _strict_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _strict_equal(value[key], item) for key, item in expected.items()
        )
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _strict_equal(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or UTC.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
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


def _semantic_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)[:-1]).hexdigest()


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _file_binding(value: Any, expected_ref: str, *, root: Path) -> bool:
    if not _exact_dict(value, {"path", "sha256"}):
        return False
    if value.get("path") != expected_ref or not isinstance(value.get("sha256"), str):
        return False
    if HEX64.fullmatch(value["sha256"]) is None:
        return False
    ref = Path(expected_ref)
    path = root / ref
    return (
        not ref.is_absolute()
        and ".." not in ref.parts
        and path.is_file()
        and not path.is_symlink()
        and _sha256(path) == value["sha256"]
    )


def _git_commit_exists(revision: Any, *, root: Path) -> bool:
    if not isinstance(revision, str) or HEX40.fullmatch(revision) is None:
        return False
    try:
        result = _run_trusted(
            GIT_PATH,
            ["--no-replace-objects", "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _git_is_ancestor(revision: Any, descendant: str, *, root: Path) -> bool:
    if not isinstance(revision, str) or HEX40.fullmatch(revision) is None:
        return False
    try:
        result = _run_trusted(
            GIT_PATH,
            ["--no-replace-objects", "merge-base", "--is-ancestor", revision, descendant],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _validate_ci_receipt(
    value: Any,
    label: str,
    revision: Any,
    expected_event: str,
    errors: list[str],
) -> None:
    keys = {
        "conclusion",
        "run_attempt",
        "exact_revision_verified",
        "run_id_sha256",
        "job_id_sha256",
        "step_count",
        "unit_test_count",
        "postgres_test_count",
        "readiness_check_count",
        "error_annotation_count",
        "revision",
        "repository",
        "ref",
        "event",
        "head_sha",
    }
    if not _exact_dict(value, keys):
        errors.append(f"{label}: CI receipt fields mismatch")
        return
    _append(
        errors,
        value.get("conclusion") == "success"
        and value.get("revision") == revision
        and value.get("head_sha") == revision
        and value.get("repository") == REPOSITORY
        and value.get("ref") == SOURCE_REF
        and value.get("event") == expected_event
        and _strict_equal(value.get("run_attempt"), 1)
        and value.get("exact_revision_verified") is True
        and _hex64(value.get("run_id_sha256"))
        and _hex64(value.get("job_id_sha256"))
        and _nonnegative_int(value.get("step_count"))
        and value["step_count"] > 0
        and _nonnegative_int(value.get("unit_test_count"))
        and value["unit_test_count"] > 0
        and _nonnegative_int(value.get("postgres_test_count"))
        and value["postgres_test_count"] > 0
        and _nonnegative_int(value.get("readiness_check_count"))
        and value["readiness_check_count"] > 0
        and _strict_equal(value.get("error_annotation_count"), 0),
        f"{label}: exact-HEAD CI did not pass",
    )


def _expected_command_binding(action: str) -> dict[str, str]:
    executor = read_frozen_executor()
    wrapper, _compressed = render_command_wrapper(action, executor)
    _content, content_sha256 = render_command_content(wrapper)
    return {
        "command_name": REQUEST_ACTIONS[action].name,
        "command_content_sha256": content_sha256,
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "executor_sha256": hashlib.sha256(executor).hexdigest(),
    }


def _file_binding_at_revision(
    value: Any, expected_ref: str, revision: Any, *, root: Path
) -> bool:
    if (
        not isinstance(revision, str)
        or HEX40.fullmatch(revision) is None
        or not _exact_dict(value, {"path", "sha256"})
        or value.get("path") != expected_ref
        or not isinstance(value.get("sha256"), str)
        or HEX64.fullmatch(value["sha256"]) is None
    ):
        return False
    try:
        result = _run_trusted(
            GIT_PATH,
            ["--no-replace-objects", "show", f"{revision}:{expected_ref}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return (
        result.returncode == 0
        and len(result.stdout) <= MAX_EVIDENCE_BYTES
        and hashlib.sha256(result.stdout).hexdigest() == value["sha256"]
    )


def _endpoint_projection(
    value: Any,
    *,
    path: str,
    status: int,
    service: str | None = None,
    state: str | None = None,
) -> bool:
    expected_keys = {"path", "status"}
    if service is not None:
        expected_keys.update({"service", "state"})
        if state == "ready":
            expected_keys.add("checks")
    if not _exact_dict(value, expected_keys):
        return False
    if value.get("path") != path or not _strict_equal(value.get("status"), status):
        return False
    if service is None:
        return True
    if value.get("service") != service or value.get("state") != state:
        return False
    if state == "ready":
        checks = value.get("checks")
        return (
            isinstance(checks, list)
            and bool(checks)
            and checks == sorted(set(checks))
            and all(isinstance(item, str) and item for item in checks)
        )
    return True


def _validate_endpoints(
    mode: str, projections: Any, errors: list[str]
) -> dict[str, str]:
    if mode not in {"api-c", "api-f"}:
        _append(errors, projections == [], f"{mode}: unexpected endpoints")
        return {}
    if not isinstance(projections, list):
        errors.append(f"{mode}: endpoint projections missing")
        return {}
    expected_count = 8 if mode == "api-c" else 5
    if len(projections) != expected_count:
        errors.append(f"{mode}: endpoint projection count mismatch")
        return {}
    _append(
        errors,
        _endpoint_projection(
            projections[0], path="/health/live", status=200,
            service="noteai-api", state="ok",
        ),
        f"{mode}: API live projection mismatch",
    )
    _append(
        errors,
        _endpoint_projection(
            projections[1], path="/health/ready", status=200,
            service="noteai-api", state="ready",
        ),
        f"{mode}: API ready projection mismatch",
    )
    hashes: dict[str, str] = {}
    for index, path in ((2, "/legal/contracts"), (3, "/billing/tiers")):
        item = projections[index]
        ok = (
            _exact_dict(item, {"path", "status", "sha256"})
            and item.get("path") == path
            and _strict_equal(item.get("status"), 200)
            and isinstance(item.get("sha256"), str)
            and HEX64.fullmatch(item["sha256"]) is not None
        )
        _append(errors, ok, f"{mode}: {path} projection mismatch")
        if ok:
            hashes[path] = item["sha256"]
    _append(
        errors,
        _strict_equal(projections[4], {
            "path": "/payments/capabilities",
            "status": 200,
            "ordering_available": False,
            "currency": "CNY",
            "auto_renewal": False,
        }),
        f"{mode}: payment capability projection mismatch",
    )
    if mode == "api-c":
        _append(
            errors,
            _endpoint_projection(
                projections[5], path="/health/live", status=200,
                service="noteai-admin", state="ok",
            ),
            "api-c: Admin live projection mismatch",
        )
        _append(
            errors,
            _endpoint_projection(
                projections[6], path="/health/ready", status=200,
                service="noteai-admin", state="ready",
            ),
            "api-c: Admin ready projection mismatch",
        )
        _append(
            errors,
            _strict_equal(projections[7], {
                "path": "/admin/capabilities",
                "status": 403,
                "authorization": "REJECTED",
            }),
            "api-c: Admin authorization projection mismatch",
        )
    return hashes


def _validate_role(value: Any, expected_role: str, label: str, errors: list[str]) -> None:
    base = {
        "role",
        "health_passed",
        "suspended_one_shot_passed",
        "expected_negative_passed",
    }
    extras = {
        "dispatcher": {"pending_outbox", "exhausted_outbox"},
        "payment": set(),
        "worker": {
            "needs_manual", "expired_ready", "stale_provider_outcome",
            "recoverable_unstarted",
        },
        "trends": {"provider_attempt_counts"},
        "tracking": {"provider_attempt_counts"},
    }[expected_role]
    if not _exact_dict(value, base | extras):
        errors.append(f"{label}: role fields mismatch")
        return
    _append(errors, value.get("role") == expected_role, f"{label}: role mismatch")
    _append(errors, value.get("health_passed") is True, f"{label}: health failed")
    _append(
        errors,
        value.get("suspended_one_shot_passed") is (expected_role != "payment"),
        f"{label}: suspended one-shot mismatch",
    )
    _append(
        errors,
        value.get("expected_negative_passed") is (expected_role == "payment"),
        f"{label}: expected-negative mismatch",
    )
    if expected_role == "dispatcher":
        _append(
            errors,
            _nonnegative_int(value.get("pending_outbox"))
            and _strict_equal(value.get("exhausted_outbox"), 0),
            f"{label}: dispatcher counters mismatch",
        )
    elif expected_role == "worker":
        _append(
            errors,
            all(_strict_equal(value.get(key), 0) for key in (
                "needs_manual", "expired_ready", "stale_provider_outcome",
            ))
            and _nonnegative_int(value.get("recoverable_unstarted")),
            f"{label}: worker counters mismatch",
        )
    elif expected_role == "trends":
        _append(
            errors,
            _strict_equal(
                value.get("provider_attempt_counts"),
                {"active": 0, "unknown": 0, "unlinked": 0},
            ),
            f"{label}: Trends provider-attempt mismatch",
        )
    elif expected_role == "tracking":
        _append(
            errors,
            _strict_equal(
                value.get("provider_attempt_counts"),
                {"active": 0, "stale": 0, "unlinked": 0},
            ),
            f"{label}: Tracking provider-attempt mismatch",
        )


def _validate_result(
    result: Any,
    *,
    action: str,
    mode: str,
    endpoint_count: int,
    roles: tuple[str, ...],
    errors: list[str],
) -> dict[str, Any]:
    shared_errors, derived = validate_executor_result(result, action)
    errors.extend(shared_errors)
    _append(
        errors,
        mode == ACTION_ROWS[[row[0] for row in ACTION_ROWS].index(action)][1]
        and endpoint_count
        == ACTION_ROWS[[row[0] for row in ACTION_ROWS].index(action)][2]
        and roles == ACTION_ROWS[[row[0] for row in ACTION_ROWS].index(action)][3],
        f"{action}: shared validator contract mismatch",
    )
    return derived


def _validate_raw_binding(
    value: Any, byte_key: str, sha_key: str, label: str, errors: list[str]
) -> None:
    _append(
        errors,
        _nonnegative_int(value.get(byte_key))
        and value[byte_key] > 0
        and _hex64(value.get(sha_key)),
        f"{label}: raw response commitment mismatch",
    )


def _validate_provider_receipt(
    receipt: Any,
    *,
    action: str,
    mode: str,
    revision: Any,
    result: Any,
    root: Path,
    errors: list[str],
) -> dict[str, str]:
    label = f"{action}/provider-receipt"
    top_keys = {
        "schema_version", "schema", "task_id", "action", "mode", "status",
        "observed_at_utc", "source_revision", "request", "pre_dispatch",
        "terminal_readback", "result_binding", "execution_boundary",
        "raw_closure", "result", "terminal_acceptance_sha256",
    }
    if not _exact_dict(receipt, top_keys):
        if isinstance(receipt, dict) and "raw_closure" not in receipt:
            errors.append(f"{label}: raw closure builder attestation missing")
        else:
            errors.append(f"{label}: fields mismatch")
        return {}
    try:
        computed_terminal_acceptance = terminal_acceptance_sha256(receipt)
    except (TypeError, ValueError, UnicodeError):
        computed_terminal_acceptance = None
    _append(
        errors,
        _strict_equal(receipt.get("schema_version"), 1)
        and receipt.get("schema") == RECEIPT_SCHEMA
        and receipt.get("task_id") == TASK_ID
        and receipt.get("action") == action
        and receipt.get("mode") == mode
        and receipt.get("status") == "PROVIDER_TERMINAL_VERIFIED"
        and isinstance(receipt.get("observed_at_utc"), str)
        and UTC.fullmatch(receipt["observed_at_utc"]) is not None
        and receipt.get("source_revision") == revision,
        f"{label}: identity mismatch",
    )
    _append(
        errors,
        _hex64(receipt.get("terminal_acceptance_sha256"))
        and receipt.get("terminal_acceptance_sha256")
        == computed_terminal_acceptance,
        f"{label}: terminal acceptance digest mismatch",
    )

    raw_closure = receipt.get("raw_closure")
    raw_closure_keys = {
        "capture_contract", "capture_file_count",
        "capture_manifest_canonical_bytes",
        "capture_manifest_canonical_sha256", "raw_body_total_bytes",
        "raw_body_aggregate_sha256", "builder", "executor_result_validator",
        "provider_fields_parsed_from_raw", "receipt_emitted_by_builder",
        "executor_result_semantics_verified",
        "provider_raw_bodies_retained_complete",
        "provider_response_projection_only",
    }
    if not _exact_dict(raw_closure, raw_closure_keys):
        errors.append(f"{label}: raw closure builder attestation missing")
    else:
        _append(
            errors,
            raw_closure.get("capture_contract") == CAPTURE_CONTRACT
            and _strict_equal(
                raw_closure.get("capture_file_count"), len(CAPTURE_FILES)
            )
            and _nonnegative_int(
                raw_closure.get("capture_manifest_canonical_bytes")
            )
            and raw_closure["capture_manifest_canonical_bytes"] > 0
            and _hex64(raw_closure.get("capture_manifest_canonical_sha256"))
            and _nonnegative_int(raw_closure.get("raw_body_total_bytes"))
            and raw_closure["raw_body_total_bytes"] > 0
            and _hex64(raw_closure.get("raw_body_aggregate_sha256"))
            and raw_closure.get("provider_fields_parsed_from_raw") is True
            and raw_closure.get("provider_raw_bodies_retained_complete") is True
            and raw_closure.get("provider_response_projection_only") is True
            and raw_closure.get("receipt_emitted_by_builder") is True
            and raw_closure.get("executor_result_semantics_verified") is True,
            f"{label}: raw closure builder attestation mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                raw_closure.get("builder"), BUILDER_REF, revision, root=root
            ),
            f"{label}: raw closure builder source binding mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                raw_closure.get("executor_result_validator"),
                VALIDATOR_REF, revision, root=root,
            ),
            f"{label}: shared result validator source binding mismatch",
        )
    _append(
        errors,
        _strict_equal(receipt.get("result"), result),
        f"{label}: builder result/main evidence mismatch",
    )

    request = receipt.get("request")
    request_keys = {
        "canonical_bytes", "canonical_sha256", "command_name",
        "command_content_sha256", "wrapper_sha256", "executor_sha256",
        "client_token_sha256", "client_token_plan_sha256",
        "predecessor_acceptance_sha256",
        "target_identity_sha256", "target_plan_slot", "target_count",
        "run_command_response_raw_bytes", "run_command_response_raw_sha256",
        "provider_request_id_sha256", "provider_command_id_sha256",
    }
    if not _exact_dict(request, request_keys):
        errors.append(f"{label}: request fields mismatch")
        return {}
    try:
        command = _expected_command_binding(action)
    except Exception:
        command = None
    expected_slot = REQUEST_ACTIONS[action].target
    _append(
        errors,
        _nonnegative_int(request.get("canonical_bytes"))
        and request["canonical_bytes"] > 0
        and _hex64(request.get("canonical_sha256"))
        and command is not None
        and all(request.get(key) == value for key, value in command.items())
        and _hex64(request.get("client_token_sha256"))
        and _hex64(request.get("client_token_plan_sha256"))
        and _hex64(request.get("predecessor_acceptance_sha256"))
        and _hex64(request.get("target_identity_sha256"))
        and request.get("target_plan_slot") == expected_slot
        and _strict_equal(request.get("target_count"), 1)
        and _hex64(request.get("provider_request_id_sha256"))
        and _hex64(request.get("provider_command_id_sha256")),
        f"{label}: exact RunCommand request commitment mismatch",
    )
    _validate_raw_binding(
        request, "run_command_response_raw_bytes",
        "run_command_response_raw_sha256", label, errors,
    )

    pre = receipt.get("pre_dispatch")
    pre_keys = {
        "all_pages", "page_number", "page_size",
        "describe_commands_request_canonical_bytes",
        "describe_commands_request_canonical_sha256",
        "describe_commands_request_id_sha256",
        "describe_commands_raw_bytes", "describe_commands_raw_sha256",
        "describe_invocations_request_canonical_bytes",
        "describe_invocations_request_canonical_sha256",
        "describe_invocations_request_id_sha256",
        "describe_invocations_raw_bytes", "describe_invocations_raw_sha256",
        "exact_command_history_count", "exact_invocation_history_count",
        "exact_name_history_count",
        "provider_client_token_readback_supported",
    }
    if not _exact_dict(pre, pre_keys):
        errors.append(f"{label}: pre-dispatch fields mismatch")
    else:
        _append(
            errors,
            pre.get("all_pages") is True
            and _strict_equal(pre.get("page_number"), 1)
            and _strict_equal(pre.get("page_size"), 50)
            and _hex64(pre.get("describe_commands_request_id_sha256"))
            and _hex64(pre.get("describe_invocations_request_id_sha256"))
            and pre.get("provider_client_token_readback_supported") is False
            and all(_strict_equal(pre.get(key), 0) for key in (
                "exact_command_history_count", "exact_invocation_history_count",
                "exact_name_history_count",
            )),
            f"{label}: pre-dispatch history was not exact zero",
        )
        _validate_raw_binding(
            pre, "describe_commands_request_canonical_bytes",
            "describe_commands_request_canonical_sha256", label, errors,
        )
        _validate_raw_binding(
            pre, "describe_commands_raw_bytes",
            "describe_commands_raw_sha256", label, errors,
        )
        _validate_raw_binding(
            pre, "describe_invocations_request_canonical_bytes",
            "describe_invocations_request_canonical_sha256", label, errors,
        )
        _validate_raw_binding(
            pre, "describe_invocations_raw_bytes",
            "describe_invocations_raw_sha256", label, errors,
        )

    terminal = receipt.get("terminal_readback")
    terminal_keys = {
        "all_pages", "page_number", "page_size",
        "describe_commands_request_canonical_bytes",
        "describe_commands_request_canonical_sha256",
        "describe_commands_request_id_sha256",
        "describe_commands_raw_bytes", "describe_commands_raw_sha256",
        "describe_invocations_request_canonical_bytes",
        "describe_invocations_request_canonical_sha256",
        "describe_invocations_request_id_sha256",
        "describe_invocations_raw_bytes", "describe_invocations_raw_sha256",
        "describe_results_request_canonical_bytes",
        "describe_results_request_canonical_sha256",
        "describe_results_request_id_sha256", "describe_results_raw_bytes",
        "describe_results_raw_sha256", "provider_command_id_sha256",
        "provider_invoke_id_sha256", "command_match_count",
        "invocation_match_count", "result_match_count", "status", "exit_code",
        "dropped_count", "repeat_count", "request_canonical_sha256",
        "provider_result_status", "provider_start_time_utc",
        "provider_finished_time_utc",
        "command_content_sha256",
        "target_identity_sha256",
        "provider_readable_run_command_field_count",
        "provider_readable_run_command_sha256",
    }
    if not _exact_dict(terminal, terminal_keys):
        errors.append(f"{label}: terminal readback fields mismatch")
    else:
        _append(
            errors,
            terminal.get("all_pages") is True
            and _strict_equal(terminal.get("page_number"), 1)
            and _strict_equal(terminal.get("page_size"), 50)
            and all(_hex64(terminal.get(key)) for key in (
                "describe_commands_request_id_sha256",
                "describe_invocations_request_id_sha256",
                "describe_results_request_id_sha256",
                "provider_command_id_sha256", "provider_invoke_id_sha256",
            ))
            and terminal.get("provider_command_id_sha256")
            == request.get("provider_command_id_sha256")
            and terminal.get("request_canonical_sha256")
            == request.get("canonical_sha256")
            and terminal.get("command_content_sha256")
            == request.get("command_content_sha256")
            and terminal.get("target_identity_sha256")
            == request.get("target_identity_sha256")
            and all(_strict_equal(terminal.get(key), 1) for key in (
                "command_match_count", "invocation_match_count",
                "result_match_count", "repeat_count",
            ))
            and terminal.get("status") == "Finished"
            and terminal.get("provider_result_status") == "Success"
            and _utc(terminal.get("provider_start_time_utc")) is not None
            and _utc(terminal.get("provider_finished_time_utc")) is not None
            and _utc(receipt.get("observed_at_utc")) is not None
            and _utc(terminal.get("provider_start_time_utc"))
            < _utc(terminal.get("provider_finished_time_utc"))
            <= _utc(receipt.get("observed_at_utc"))
            and _strict_equal(terminal.get("exit_code"), 0)
            and _strict_equal(terminal.get("dropped_count"), 0)
            and _strict_equal(
                terminal.get("provider_readable_run_command_field_count"), 7
            )
            and _hex64(
                terminal.get("provider_readable_run_command_sha256")
            ),
            f"{label}: terminal readback mismatch",
        )
        for byte_key, sha_key in (
            (
                "describe_commands_request_canonical_bytes",
                "describe_commands_request_canonical_sha256",
            ),
            ("describe_commands_raw_bytes", "describe_commands_raw_sha256"),
            (
                "describe_invocations_request_canonical_bytes",
                "describe_invocations_request_canonical_sha256",
            ),
            ("describe_invocations_raw_bytes", "describe_invocations_raw_sha256"),
            (
                "describe_results_request_canonical_bytes",
                "describe_results_request_canonical_sha256",
            ),
            ("describe_results_raw_bytes", "describe_results_raw_sha256"),
        ):
            _validate_raw_binding(terminal, byte_key, sha_key, label, errors)

    result_binding = receipt.get("result_binding")
    result_keys = {
        "stdout_canonical_bytes", "stdout_canonical_sha256",
        "result_semantic_sha256", "stderr_bytes", "stderr_sha256",
        "schema", "task_id", "status", "mode",
    }
    if not _exact_dict(result_binding, result_keys):
        errors.append(f"{label}: result binding fields mismatch")
    else:
        try:
            stdout = _canonical_bytes(result)
            semantic = _semantic_sha256(result)
        except (TypeError, ValueError, UnicodeError):
            stdout = b""
            semantic = ""
        _append(
            errors,
            result_binding.get("stdout_canonical_bytes") == len(stdout)
            and result_binding.get("stdout_canonical_sha256")
            == hashlib.sha256(stdout).hexdigest()
            and result_binding.get("result_semantic_sha256") == semantic
            and _strict_equal(result_binding.get("stderr_bytes"), 0)
            and result_binding.get("stderr_sha256") == EMPTY_SHA256
            and result_binding.get("schema") == RESULT_SCHEMA
            and result_binding.get("task_id") == TASK_ID
            and result_binding.get("status") == "PASS"
            and result_binding.get("mode") == mode,
            f"{label}: stdout/result binding mismatch",
        )

    boundary = receipt.get("execution_boundary")
    _append(
        errors,
        _strict_equal(boundary, {
            "dispatch_count": 1,
            "automatic_retry_count": 0,
            "same_request_resubmit_allowed": False,
            "same_invocation_replay_allowed": False,
            "provider_unknown": False,
            "root_only_raw_material_retained": True,
            "raw_provider_body_value_emitted_count": 0,
            "raw_provider_body_commitment_count": len(
                PROVIDER_RAW_RESPONSE_FILES
            ),
            "provider_request_value_emitted_count": 0,
            "provider_request_commitment_count": len(PROVIDER_REQUEST_FILES),
            "derived_client_token_commitment_count": 1,
            "local_o_excl_plan_nonce_required": True,
            "provider_client_token_readback_supported": False,
            "root_only_plan_input_value_emitted_count": 0,
            "root_only_plan_input_commitment_count": 1,
            "provider_identifier_value_emitted_count": 0,
            "provider_identifier_commitment_count": 8,
            "secret_value_count": 0,
        }),
        f"{label}: no-replay/retention boundary mismatch",
    )
    return {
        "request_sha256": request.get("canonical_sha256"),
        "client_token_sha256": request.get("client_token_sha256"),
        "client_token_plan_sha256": request.get("client_token_plan_sha256"),
        "predecessor_acceptance_sha256": request.get(
            "predecessor_acceptance_sha256"
        ),
        "terminal_acceptance_sha256": receipt.get(
            "terminal_acceptance_sha256"
        ),
        "provider_start_time_utc": (
            terminal.get("provider_start_time_utc")
            if isinstance(terminal, dict) else None
        ),
        "provider_finished_time_utc": (
            terminal.get("provider_finished_time_utc")
            if isinstance(terminal, dict) else None
        ),
        "observed_at_utc": receipt.get("observed_at_utc"),
        "target_identity_sha256": request.get("target_identity_sha256"),
        "provider_request_id_sha256": request.get("provider_request_id_sha256"),
        "provider_command_id_sha256": request.get("provider_command_id_sha256"),
        "provider_invoke_id_sha256": (
            terminal.get("provider_invoke_id_sha256")
            if isinstance(terminal, dict) else None
        ),
        "stdout_sha256": (
            result_binding.get("stdout_canonical_sha256")
            if isinstance(result_binding, dict) else None
        ),
    }


def validate_document(
    payload: dict[str, Any],
    *,
    root: Path = ROOT,
    receipt_payloads: dict[str, dict[str, Any]] | None = None,
    expected_item26_terminal_acceptance_sha256: str | None = None,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    item26_digest: str | None = None
    if not isinstance(payload, dict):
        return ["evidence root must be an object"]
    _append(errors, set(payload) == TOP_LEVEL_KEYS, "top-level fields mismatch")
    _append(
        errors, _strict_equal(payload.get("schema_version"), 1),
        "schema version mismatch",
    )
    _append(errors, payload.get("task_id") == TASK_ID, "task id mismatch")
    _append(errors, payload.get("status") == "VERIFIED_CLEAN", "status mismatch")
    _append(
        errors,
        isinstance(payload.get("observed_at_utc"), str)
        and UTC.fullmatch(payload["observed_at_utc"]) is not None,
        "UTC observation timestamp required",
    )

    source = payload.get("source_binding")
    source_keys = {
        "release_revision", "branch", "origin_branch_ref",
        "checkpoint_pushed", "exact_head_ci", "item26_terminal_verified",
        "item26_terminal_acceptance_sha256", "fresh_runtime_baseline_sha256",
        "executor", "request_renderer", "raw_closure_builder",
        "executor_result_validator", "external_authority_verifier",
        "action_order",
    }
    _append(errors, _exact_dict(source, source_keys), "source binding fields mismatch")
    if isinstance(source, dict):
        revision = source.get("release_revision")
        _append(
            errors,
            _git_commit_exists(revision, root=root),
            "release revision mismatch",
        )
        origin_ref = f"refs/remotes/origin/{SOURCE_BRANCH}"
        _append(
            errors,
            source.get("branch") == SOURCE_BRANCH
            and source.get("origin_branch_ref") == origin_ref
            and source.get("checkpoint_pushed") is True
            and _git_is_ancestor(revision, "HEAD", root=root)
            and _git_is_ancestor(revision, origin_ref, root=root),
            "source revision origin ancestry/projection mismatch",
        )
        ci = source.get("exact_head_ci")
        if not _exact_dict(ci, {"push", "pull_request", "parity_verified"}):
            errors.append("exact-HEAD CI fields mismatch")
        else:
            _validate_ci_receipt(
                ci.get("push"), "push", revision, "push", errors
            )
            _validate_ci_receipt(
                ci.get("pull_request"), "pull_request", revision,
                "pull_request", errors,
            )
            _append(
                errors,
                ci.get("parity_verified") is True
                and all(
                    ci["push"].get(key) == ci["pull_request"].get(key)
                    for key in (
                        "step_count", "unit_test_count", "postgres_test_count",
                        "readiness_check_count", "error_annotation_count",
                    )
                ) if isinstance(ci.get("push"), dict)
                and isinstance(ci.get("pull_request"), dict) else False,
                "push/pull-request CI parity mismatch",
            )
            ci_ids = [
                ci[kind].get(field)
                for kind in ("push", "pull_request")
                for field in ("run_id_sha256", "job_id_sha256")
                if isinstance(ci.get(kind), dict)
            ]
            _append(
                errors,
                len(ci_ids) == 4
                and all(_hex64(value) for value in ci_ids)
                and len(set(ci_ids)) == 4,
                "push/pull-request CI identity commitment mismatch",
            )
        item26_digest = source.get("item26_terminal_acceptance_sha256")
        _append(
            errors,
            source.get("item26_terminal_verified") is True
            and _hex64(item26_digest)
            and (
                expected_item26_terminal_acceptance_sha256 is None
                or item26_digest == expected_item26_terminal_acceptance_sha256
            ),
            "Item26 terminal evidence binding mismatch",
        )
        _append(
            errors,
            _hex64(source.get("fresh_runtime_baseline_sha256")),
            "fresh runtime baseline commitment missing",
        )
        _append(
            errors,
            _file_binding_at_revision(
                source.get("executor"), EXECUTOR_REF, revision, root=root
            ),
            "executor revision binding mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                source.get("request_renderer"), RENDERER_REF, revision,
                root=root,
            ),
            "request renderer revision binding mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                source.get("raw_closure_builder"), BUILDER_REF, revision,
                root=root,
            ),
            "raw closure builder revision binding mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                source.get("executor_result_validator"), VALIDATOR_REF,
                revision, root=root,
            ),
            "shared result validator revision binding mismatch",
        )
        _append(
            errors,
            _file_binding_at_revision(
                source.get("external_authority_verifier"),
                AUTHORITY_VERIFIER_REF, revision, root=root,
            ),
            "external authority verifier revision binding mismatch",
        )
        _append(
            errors,
            _strict_equal(
                source.get("action_order"), [row[0] for row in ACTION_ROWS]
            ),
            "action order binding mismatch",
        )

    if receipt_payloads is None:
        try:
            receipt_payloads = _load_provider_receipts(root)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"cannot load provider receipt closure: {exc}")
            receipt_payloads = {}
    _append(
        errors,
        isinstance(receipt_payloads, dict)
        and set(receipt_payloads) == set(RECEIPT_REFS),
        "provider receipt closure actions mismatch",
    )

    invocations = payload.get("invocations")
    derived: list[dict[str, int]] = []
    receipt_commitments: list[dict[str, str]] = []
    if not isinstance(invocations, list) or len(invocations) != len(ACTION_ROWS):
        errors.append("invocation count mismatch")
    else:
        for ordinal, (invocation, row) in enumerate(zip(invocations, ACTION_ROWS), 1):
            action, mode, endpoint_count, roles = row
            invocation_keys = {
                "ordinal", "action", "mode", "provider_terminal_status",
                "provider_command_count", "provider_invocation_count",
                "provider_result_count", "exit_code", "dropped_count",
                "repeat_count", "automatic_retry_count",
                "same_invocation_replay_allowed", "command_name",
                "command_content_sha256", "wrapper_sha256",
                "executor_sha256", "receipt_ref", "receipt_file_sha256",
                "receipt_semantic_sha256", "request_canonical_bytes",
                "request_canonical_sha256", "client_token_sha256",
                "client_token_plan_sha256", "target_identity_sha256",
                "provider_request_id_sha256", "provider_command_id_sha256",
                "provider_invoke_id_sha256", "stdout_canonical_bytes",
                "stdout_canonical_sha256", "predecessor_acceptance_sha256",
                "terminal_acceptance_sha256", "provider_result_status",
                "provider_start_time_utc", "provider_finished_time_utc",
                "observed_at_utc", "result",
            }
            if not _exact_dict(invocation, invocation_keys):
                errors.append(f"{action}: invocation fields mismatch")
                continue
            _append(
                errors,
                _strict_equal(invocation.get("ordinal"), ordinal)
                and invocation.get("action") == action
                and invocation.get("mode") == mode,
                f"{action}: invocation identity mismatch",
            )
            _append(
                errors,
                invocation.get("provider_terminal_status") == "Finished"
                and invocation.get("provider_result_status") == "Success"
                and _strict_equal(invocation.get("provider_command_count"), 1)
                and _strict_equal(invocation.get("provider_invocation_count"), 1)
                and _strict_equal(invocation.get("provider_result_count"), 1)
                and _strict_equal(invocation.get("exit_code"), 0)
                and _strict_equal(invocation.get("dropped_count"), 0)
                and _strict_equal(invocation.get("repeat_count"), 1)
                and _strict_equal(invocation.get("automatic_retry_count"), 0)
                and invocation.get("same_invocation_replay_allowed") is False,
                f"{action}: provider terminal result mismatch",
            )
            try:
                command_binding = _expected_command_binding(action)
            except Exception:
                command_binding = None
            _append(
                errors,
                command_binding is not None
                and all(
                    invocation.get(key) == value
                    for key, value in command_binding.items()
                ),
                f"{action}: command content binding mismatch",
            )
            receipt = receipt_payloads.get(action)
            receipt_ref = RECEIPT_REFS[action]
            receipt_file_sha = (
                hashlib.sha256(_canonical_bytes(receipt)).hexdigest()
                if isinstance(receipt, dict) else None
            )
            receipt_semantic_sha = (
                _semantic_sha256(receipt) if isinstance(receipt, dict) else None
            )
            _append(
                errors,
                invocation.get("receipt_ref") == receipt_ref
                and invocation.get("receipt_file_sha256") == receipt_file_sha
                and invocation.get("receipt_semantic_sha256")
                == receipt_semantic_sha,
                f"{action}: provider receipt file binding mismatch",
            )
            receipt_binding = _validate_provider_receipt(
                receipt, action=action, mode=mode, revision=revision,
                result=invocation.get("result"), root=root, errors=errors,
            )
            receipt_commitments.append(receipt_binding)
            if isinstance(receipt, dict):
                request = receipt.get("request") or {}
                result_binding = receipt.get("result_binding") or {}
                terminal = receipt.get("terminal_readback") or {}
                _append(
                    errors,
                    _strict_equal(
                        invocation.get("request_canonical_bytes"),
                        request.get("canonical_bytes"),
                    )
                    and invocation.get("request_canonical_sha256")
                    == request.get("canonical_sha256")
                    and invocation.get("client_token_sha256")
                    == request.get("client_token_sha256")
                    and invocation.get("client_token_plan_sha256")
                    == request.get("client_token_plan_sha256")
                    and invocation.get("predecessor_acceptance_sha256")
                    == request.get("predecessor_acceptance_sha256")
                    and invocation.get("terminal_acceptance_sha256")
                    == receipt.get("terminal_acceptance_sha256")
                    and invocation.get("target_identity_sha256")
                    == request.get("target_identity_sha256")
                    and invocation.get("provider_request_id_sha256")
                    == request.get("provider_request_id_sha256")
                    and invocation.get("provider_command_id_sha256")
                    == request.get("provider_command_id_sha256")
                    and invocation.get("provider_invoke_id_sha256")
                    == terminal.get("provider_invoke_id_sha256")
                    and invocation.get("provider_terminal_status")
                    == terminal.get("status")
                    and invocation.get("provider_result_status")
                    == terminal.get("provider_result_status")
                    and invocation.get("provider_start_time_utc")
                    == terminal.get("provider_start_time_utc")
                    and invocation.get("provider_finished_time_utc")
                    == terminal.get("provider_finished_time_utc")
                    and invocation.get("observed_at_utc")
                    == receipt.get("observed_at_utc")
                    and _strict_equal(
                        invocation.get("exit_code"), terminal.get("exit_code")
                    )
                    and _strict_equal(
                        invocation.get("dropped_count"),
                        terminal.get("dropped_count"),
                    )
                    and _strict_equal(
                        invocation.get("repeat_count"),
                        terminal.get("repeat_count"),
                    )
                    and _strict_equal(
                        invocation.get("stdout_canonical_bytes"),
                        result_binding.get("stdout_canonical_bytes"),
                    )
                    and invocation.get("stdout_canonical_sha256")
                    == result_binding.get("stdout_canonical_sha256"),
                    f"{action}: main evidence/provider receipt mismatch",
                )
            derived.append(_validate_result(
                invocation.get("result"), action=action, mode=mode,
                endpoint_count=endpoint_count, roles=roles, errors=errors,
            ))

    if len(receipt_commitments) == len(ACTION_ROWS) and all(receipt_commitments):
        for key in (
            "request_sha256", "client_token_sha256", "target_identity_sha256",
            "provider_request_id_sha256", "provider_command_id_sha256",
            "provider_invoke_id_sha256", "stdout_sha256",
        ):
            values = [item.get(key) for item in receipt_commitments]
            _append(
                errors,
                all(_hex64(value) for value in values)
                and len(set(values)) == len(ACTION_ROWS),
                f"provider receipt {key} uniqueness mismatch",
            )
        token_plans = [
            item.get("client_token_plan_sha256") for item in receipt_commitments
        ]
        _append(
            errors,
            len(token_plans) == len(ACTION_ROWS)
            and all(_hex64(value) for value in token_plans)
            and len(set(token_plans)) == len(ACTION_ROWS),
            "provider receipt token-plan binding mismatch",
        )
        expected_predecessor = item26_digest
        previous_finished: datetime | None = None
        previous_observed: datetime | None = None
        for item, (action, _mode, _count, _roles) in zip(
            receipt_commitments, ACTION_ROWS
        ):
            start = _utc(item.get("provider_start_time_utc"))
            finished = _utc(item.get("provider_finished_time_utc"))
            observed = _utc(item.get("observed_at_utc"))
            _append(
                errors,
                _hex64(expected_predecessor)
                and item.get("predecessor_acceptance_sha256")
                == expected_predecessor
                and _hex64(item.get("terminal_acceptance_sha256"))
                and PREDECESSOR_ACCEPTANCE_SOURCES[action]
                == (
                    "item26_terminal_acceptance" if action == "api_c"
                    else ACTION_ROWS[ACTION_ORDER.index(action) - 1][0]
                    + "_terminal_acceptance"
                ),
                f"{action}: predecessor terminal acceptance chain mismatch",
            )
            _append(
                errors,
                start is not None
                and finished is not None
                and observed is not None
                and start < finished <= observed
                and (
                    previous_finished is None or previous_finished < start
                )
                and (
                    previous_observed is None or previous_observed < observed
                ),
                f"{action}: provider terminal timestamps are not strictly ordered",
            )
            expected_predecessor = item.get("terminal_acceptance_sha256")
            previous_finished = finished
            previous_observed = observed
        evidence_observed = _utc(payload.get("observed_at_utc"))
        _append(
            errors,
            previous_observed is not None
            and evidence_observed is not None
            and previous_observed < evidence_observed,
            "provider receipt/evidence timestamps are not strictly ordered",
        )

    hashes = [
        item.get("hash:/legal/contracts")
        for item in derived[:2]
        if isinstance(item, dict)
    ]
    tiers = [
        item.get("hash:/billing/tiers")
        for item in derived[:2]
        if isinstance(item, dict)
    ]
    _append(
        errors,
        len(hashes) == 2 and hashes[0] == hashes[1]
        and len(tiers) == 2 and tiers[0] == tiers[1],
        "API-C/API-F contract projection parity mismatch",
    )

    expected_aggregate = {
        "command_count": 4,
        "invocation_count": 4,
        "terminal_result_count": 4,
        "pass_count": 4,
        "loopback_endpoint_count": 13,
        "role_count": 6,
        "service_start_count": 6,
        "service_stop_count": 6,
        "provider_call_count": 0,
        "provider_attempt_count": 0,
        "oss_mutation_count": 0,
        "production_database_mutation_count": 0,
        "synthetic_record_count": 0,
        "public_request_count": 0,
        "public_listener_count": 0,
        "automatic_retry_count": 0,
        "distinct_target_plan_slot_count": 4,
        "client_token_plan_count": 4,
        "unique_client_token_count": 4,
        "fresh_pre_dispatch_history_count": 0,
    }
    _append(
        errors,
        _strict_equal(payload.get("aggregate"), expected_aggregate),
        "aggregate mismatch",
    )
    _append(
        errors,
        _strict_equal(payload.get("final_runtime_state"), {
            "dormant_unit_count": 6,
            "dormant_inactive_dead_disabled_count": 6,
            "task_root_residue_count": 0,
            "owned_container_residue_count": 0,
            "active_runtime_identity_unchanged": True,
            "original_state_restored": True,
            "api_c_api_healthy": True,
            "api_c_admin_healthy": True,
            "api_f_api_healthy": True,
            "new_public_listener_count": 0,
        }),
        "final runtime state mismatch",
    )
    _append(
        errors,
        _strict_equal(payload.get("mutation_counters"), {
            "production_database_mutation_count": 0,
            "provider_attempt_count": 0,
            "provider_call_count": 0,
            "oss_mutation_count": 0,
            "synthetic_record_count": 0,
            "unit_file_write_count": 0,
            "service_enable_count": 0,
            "public_request_count": 0,
        }),
        "mutation counters mismatch",
    )
    _append(
        errors,
        _strict_equal(payload.get("cost_and_data_boundary"), {
            "incremental_cost_cny": 0,
            "paid_resource_create_count": 0,
            "real_supplier_call_count": 0,
            "production_business_row_write_count": 0,
            "public_traffic_change_count": 0,
        }),
        "cost/data boundary mismatch",
    )
    _append(
        errors,
        _strict_equal(payload.get("secret_free_evidence"), {
            "secret_value_count": 0,
            "private_key_value_count": 0,
            "complete_connection_string_count": 0,
            "resource_id_value_count": 0,
            "private_address_value_count": 0,
            "endpoint_value_count": 0,
            "raw_provider_body_value_emitted_count": 0,
            "raw_provider_body_commitment_count": len(
                PROVIDER_RAW_RESPONSE_FILES
            ) * 4,
            "provider_request_value_emitted_count": 0,
            "provider_request_commitment_count": len(
                PROVIDER_REQUEST_FILES
            ) * 4,
            "root_only_plan_input_value_emitted_count": 0,
            "root_only_plan_input_commitment_count": 4,
        }),
        "Secret-free evidence boundary mismatch",
    )
    _append(
        errors,
        _strict_equal(
            payload.get("readiness"), expected_readiness or DEFAULT_READINESS
        ),
        "readiness transition mismatch",
    )
    return errors


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
        raise ValueError("evidence size/encoding invalid")
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if not isinstance(payload, dict):
        raise ValueError("evidence root must be an object")
    return payload


def _load_provider_receipts(root: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for action, ref in RECEIPT_REFS.items():
        path = root / ref
        raw = path.read_bytes()
        if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
            raise ValueError(f"{action}: receipt size/encoding invalid")
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_no_duplicates
        )
        if not isinstance(payload, dict):
            raise ValueError(f"{action}: receipt root must be an object")
        if raw != _canonical_bytes(payload):
            raise ValueError(f"{action}: receipt must be canonical JSON")
        receipts[action] = payload
    return receipts


def _provider_authority_projection(
    receipts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    previous_acceptance: str | None = None
    previous_finished: datetime | None = None
    previous_observed: datetime | None = None
    for ordinal, (action, _mode, _count, _roles) in enumerate(ACTION_ROWS, 1):
        receipt = receipts.get(action)
        if not isinstance(receipt, dict):
            raise ValueError("provider authority receipt missing")
        raw = receipt.get("raw_closure")
        request = receipt.get("request")
        pre = receipt.get("pre_dispatch")
        terminal = receipt.get("terminal_readback")
        result = receipt.get("result_binding")
        if not all(isinstance(item, dict) for item in (
            raw, request, pre, terminal, result,
        )):
            raise ValueError("provider authority receipt projection missing")
        predecessor = request.get("predecessor_acceptance_sha256")
        acceptance = receipt.get("terminal_acceptance_sha256")
        start = _utc(terminal.get("provider_start_time_utc"))
        finished = _utc(terminal.get("provider_finished_time_utc"))
        observed = _utc(receipt.get("observed_at_utc"))
        if (
            not _hex64(predecessor)
            or not _hex64(acceptance)
            or (previous_acceptance is not None and predecessor != previous_acceptance)
            or start is None
            or finished is None
            or observed is None
            or not start < finished <= observed
            or (previous_finished is not None and not previous_finished < start)
            or (previous_observed is not None and not previous_observed < observed)
        ):
            raise ValueError("provider authority action chain/time ordering mismatch")
        actions.append({
            "ordinal": ordinal,
            "action": action,
            "source_revision": receipt.get("source_revision"),
            "predecessor_acceptance_source": (
                PREDECESSOR_ACCEPTANCE_SOURCES[action]
            ),
            "predecessor_acceptance_sha256": predecessor,
            "terminal_acceptance_sha256": acceptance,
            "provider_terminal_status": terminal.get("status"),
            "provider_result_status": terminal.get("provider_result_status"),
            "provider_start_time_utc": terminal.get("provider_start_time_utc"),
            "provider_finished_time_utc": terminal.get(
                "provider_finished_time_utc"
            ),
            "observed_at_utc": receipt.get("observed_at_utc"),
            "capture_manifest_canonical_sha256": raw.get(
                "capture_manifest_canonical_sha256"
            ),
            "raw_body_aggregate_sha256": raw.get("raw_body_aggregate_sha256"),
            "request_canonical_sha256": request.get("canonical_sha256"),
            "run_command_response_raw_sha256": request.get(
                "run_command_response_raw_sha256"
            ),
            "pre_describe_commands_request_sha256": pre.get(
                "describe_commands_request_canonical_sha256"
            ),
            "pre_describe_commands_response_sha256": pre.get(
                "describe_commands_raw_sha256"
            ),
            "pre_describe_invocations_request_sha256": pre.get(
                "describe_invocations_request_canonical_sha256"
            ),
            "pre_describe_invocations_response_sha256": pre.get(
                "describe_invocations_raw_sha256"
            ),
            "terminal_describe_commands_request_sha256": terminal.get(
                "describe_commands_request_canonical_sha256"
            ),
            "terminal_describe_commands_response_sha256": terminal.get(
                "describe_commands_raw_sha256"
            ),
            "terminal_describe_invocations_request_sha256": terminal.get(
                "describe_invocations_request_canonical_sha256"
            ),
            "terminal_describe_invocations_response_sha256": terminal.get(
                "describe_invocations_raw_sha256"
            ),
            "terminal_describe_results_request_sha256": terminal.get(
                "describe_results_request_canonical_sha256"
            ),
            "terminal_describe_results_response_sha256": terminal.get(
                "describe_results_raw_sha256"
            ),
            "provider_request_id_sha256": request.get(
                "provider_request_id_sha256"
            ),
            "provider_command_id_sha256": request.get(
                "provider_command_id_sha256"
            ),
            "provider_invoke_id_sha256": terminal.get(
                "provider_invoke_id_sha256"
            ),
            "stdout_canonical_sha256": result.get("stdout_canonical_sha256"),
        })
        previous_acceptance = acceptance
        previous_finished = finished
        previous_observed = observed
    artifact = hashlib.sha256(_canonical_bytes(actions)).hexdigest()
    return {
        "schema_version": 1,
        "schema": "noteai.item27.provider-authority-export.v1",
        "task_id": TASK_ID,
        "status": "PROVIDER_EXPORT_VERIFIED",
        "immutable_artifact_sha256": artifact,
        "actions": actions,
    }


def _load_terminal_checkpoint(root: Path) -> dict[str, Any]:
    path = root / TERMINAL_CHECKPOINT_REF
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
        raise ValueError("terminal checkpoint size/encoding invalid")
    payload = json.loads(raw.decode("ascii"), object_pairs_hook=_no_duplicates)
    if not isinstance(payload, dict):
        raise ValueError("terminal checkpoint root must be an object")
    if raw != _canonical_bytes(payload):
        raise ValueError("terminal checkpoint must be canonical JSON")
    return payload


def _validate_terminal_checkpoint(
    checkpoint: Any,
    payload: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    *,
    root: Path,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    keys = {
        "schema_version", "schema", "task_id", "status", "observed_at_utc",
        "source_revision", "evidence_revision", "branch", "origin_branch_ref",
        "checkpoint_pushed", "exact_head_ci", "blob_bindings",
    }
    if not _exact_dict(checkpoint, keys):
        return ["Item27 terminal checkpoint fields mismatch"], None
    source = payload.get("source_binding")
    source_revision = (
        source.get("release_revision") if isinstance(source, dict) else None
    )
    evidence_revision = checkpoint.get("evidence_revision")
    origin_ref = f"refs/remotes/origin/{SOURCE_BRANCH}"
    _append(
        errors,
        _strict_equal(checkpoint.get("schema_version"), 1)
        and checkpoint.get("schema") == TERMINAL_CHECKPOINT_SCHEMA
        and checkpoint.get("task_id") == TASK_ID
        and checkpoint.get("status") == "EVIDENCE_CHECKPOINT_CI_VERIFIED"
        and isinstance(checkpoint.get("observed_at_utc"), str)
        and UTC.fullmatch(checkpoint["observed_at_utc"]) is not None
        and checkpoint.get("source_revision") == source_revision
        and isinstance(evidence_revision, str)
        and HEX40.fullmatch(evidence_revision) is not None
        and evidence_revision != source_revision
        and checkpoint.get("branch") == SOURCE_BRANCH
        and checkpoint.get("origin_branch_ref") == origin_ref
        and checkpoint.get("checkpoint_pushed") is True
        and _git_commit_exists(evidence_revision, root=root)
        and _git_is_ancestor(source_revision, evidence_revision, root=root)
        and _git_is_ancestor(evidence_revision, "HEAD", root=root)
        and _git_is_ancestor(evidence_revision, origin_ref, root=root),
        "Item27 evidence revision origin ancestry/projection mismatch",
    )
    ci = checkpoint.get("exact_head_ci")
    if not _exact_dict(ci, {"push", "pull_request", "parity_verified"}):
        errors.append("Item27 terminal exact-HEAD CI fields mismatch")
    else:
        _validate_ci_receipt(
            ci.get("push"), "terminal/push", evidence_revision, "push", errors
        )
        _validate_ci_receipt(
            ci.get("pull_request"), "terminal/pull_request",
            evidence_revision, "pull_request", errors,
        )
        _append(
            errors,
            ci.get("parity_verified") is True
            and isinstance(ci.get("push"), dict)
            and isinstance(ci.get("pull_request"), dict)
            and all(
                ci["push"].get(key) == ci["pull_request"].get(key)
                for key in (
                    "step_count", "unit_test_count", "postgres_test_count",
                    "readiness_check_count", "error_annotation_count",
                )
            )
            and len({
                ci[kind].get(field)
                for kind in ("push", "pull_request")
                for field in ("run_id_sha256", "job_id_sha256")
            }) == 4,
            "Item27 terminal push/pull-request CI parity mismatch",
        )

    expected_refs = {
        EVIDENCE_REF,
        *RECEIPT_REFS.values(),
        BUILDER_REF,
        VALIDATOR_REF,
        AUTHORITY_VERIFIER_REF,
        "tools/verify_internal_zero_provider_smoke_evidence.py",
        EXECUTOR_REF,
        RENDERER_REF,
    }
    bindings = checkpoint.get("blob_bindings")
    if (
        not isinstance(bindings, list)
        or len(bindings) != len(expected_refs)
        or any(not _exact_dict(item, {"path", "sha256"}) for item in bindings)
        or {item.get("path") for item in bindings} != expected_refs
    ):
        errors.append("Item27 terminal evidence blob bindings mismatch")
    else:
        by_ref = {item["path"]: item for item in bindings}
        for ref in expected_refs:
            _append(
                errors,
                _file_binding_at_revision(
                    by_ref[ref], ref, evidence_revision, root=root
                ),
                f"Item27 terminal revision blob mismatch: {ref}",
            )
        current_payloads = {
            EVIDENCE_REF: _canonical_bytes(payload),
            **{
                RECEIPT_REFS[action]: _canonical_bytes(receipt)
                for action, receipt in receipts.items()
            },
        }
        for ref, raw in current_payloads.items():
            _append(
                errors,
                by_ref.get(ref, {}).get("sha256") == hashlib.sha256(raw).hexdigest(),
                f"Item27 terminal/current evidence mismatch: {ref}",
            )
    return errors, evidence_revision if not errors else None


def _validate_external_ci_authority(
    authority: Any,
    payload: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    checkpoint: dict[str, Any],
    *,
    root: Path,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    keys = {
        "schema_version", "schema", "task_id", "status",
        "immutable_artifact_sha256", "source_revision", "evidence_revision",
        "terminal_revision", "final_revision", "stage_ci",
        "final_blob_bindings",
    }
    if not _exact_dict(authority, keys):
        return ["Item27 signed CI authority fields mismatch"], None
    source = payload.get("source_binding")
    source_revision = (
        source.get("release_revision") if isinstance(source, dict) else None
    )
    evidence_revision = checkpoint.get("evidence_revision")
    terminal_revision = authority.get("terminal_revision")
    final_revision = authority.get("final_revision")
    revisions = (
        source_revision, evidence_revision, terminal_revision, final_revision,
    )
    _append(
        errors,
        _strict_equal(authority.get("schema_version"), 1)
        and authority.get("schema") == "noteai.item27.ci-authority-export.v1"
        and authority.get("task_id") == TASK_ID
        and authority.get("status") == "ALL_EXACT_REVISIONS_CI_VERIFIED"
        and _hex64(authority.get("immutable_artifact_sha256"))
        and authority.get("source_revision") == source_revision
        and authority.get("evidence_revision") == evidence_revision
        and all(isinstance(value, str) and HEX40.fullmatch(value) for value in revisions)
        and len(set(revisions)) == 4
        and all(_git_commit_exists(value, root=root) for value in revisions)
        and _git_is_ancestor(source_revision, evidence_revision, root=root)
        and _git_is_ancestor(evidence_revision, terminal_revision, root=root)
        and _git_is_ancestor(terminal_revision, final_revision, root=root)
        and _git_is_ancestor(final_revision, "HEAD", root=root)
        and _git_is_ancestor(
            final_revision, f"refs/remotes/origin/{SOURCE_BRANCH}", root=root
        ),
        "Item27 source/evidence/terminal/final ancestry mismatch",
    )
    stages = authority.get("stage_ci")
    if not _exact_dict(stages, {"source", "evidence", "terminal", "final"}):
        errors.append("Item27 signed stage CI fields mismatch")
    else:
        expected_projections = {
            "source": source.get("exact_head_ci") if isinstance(source, dict) else None,
            "evidence": checkpoint.get("exact_head_ci"),
        }
        all_ci_ids: list[str] = []
        for stage, revision in zip(
            ("source", "evidence", "terminal", "final"), revisions
        ):
            pair = stages.get(stage)
            if not _exact_dict(pair, {"push", "pull_request", "parity_verified"}):
                errors.append(f"{stage}: signed CI pair fields mismatch")
                continue
            _validate_ci_receipt(
                pair.get("push"), f"authority/{stage}/push", revision,
                "push", errors,
            )
            _validate_ci_receipt(
                pair.get("pull_request"),
                f"authority/{stage}/pull_request", revision,
                "pull_request", errors,
            )
            _append(
                errors,
                pair.get("parity_verified") is True
                and isinstance(pair.get("push"), dict)
                and isinstance(pair.get("pull_request"), dict)
                and all(
                    pair["push"].get(key) == pair["pull_request"].get(key)
                    for key in (
                        "step_count", "unit_test_count", "postgres_test_count",
                        "readiness_check_count", "error_annotation_count",
                    )
                ),
                f"authority/{stage}: push/pull CI parity mismatch",
            )
            for kind in ("push", "pull_request"):
                row = pair.get(kind)
                if isinstance(row, dict):
                    all_ci_ids.extend([
                        row.get("run_id_sha256"), row.get("job_id_sha256")
                    ])
        _append(
            errors,
            len(all_ci_ids) == 16
            and all(_hex64(value) for value in all_ci_ids)
            and len(set(all_ci_ids)) == 16,
            "signed CI authority identities are not globally unique",
        )
        for stage, projection in expected_projections.items():
            _append(
                errors,
                _strict_equal(stages.get(stage), projection),
                f"{stage}: local CI projection/signed authority mismatch",
            )

    final_refs = {
        EVIDENCE_REF,
        TERMINAL_CHECKPOINT_REF,
        *RECEIPT_REFS.values(),
        EXECUTOR_REF,
        RENDERER_REF,
        BUILDER_REF,
        VALIDATOR_REF,
        AUTHORITY_VERIFIER_REF,
        "tools/verify_internal_zero_provider_smoke_evidence.py",
    }
    bindings = authority.get("final_blob_bindings")
    if (
        not isinstance(bindings, list)
        or len(bindings) != len(final_refs)
        or any(not _exact_dict(item, {"path", "sha256"}) for item in bindings)
        or {item.get("path") for item in bindings} != final_refs
    ):
        errors.append("Item27 final trust-root blob bindings mismatch")
    else:
        by_ref = {item["path"]: item for item in bindings}
        for ref in final_refs:
            _append(
                errors,
                _file_binding_at_revision(
                    by_ref[ref], ref, final_revision, root=root
                )
                and _file_binding(by_ref[ref], ref, root=root),
                f"Item27 final trust-root blob mismatch: {ref}",
            )
        terminal_binding = by_ref[TERMINAL_CHECKPOINT_REF]
        _append(
            errors,
            _file_binding_at_revision(
                terminal_binding, TERMINAL_CHECKPOINT_REF,
                terminal_revision, root=root,
            ),
            "Item27 terminal revision checkpoint blob mismatch",
        )
    return errors, final_revision if not errors else None


def _validate_frozen_closure(
    evidence_path: Path,
    payload: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    terminal_checkpoint: dict[str, Any],
    *,
    root: Path,
) -> list[str]:
    errors: list[str] = []
    roots = [
        EXPECTED_EVIDENCE_FILE_SHA256,
        EXPECTED_EVIDENCE_SEMANTIC_SHA256,
        *EXPECTED_RECEIPT_FILE_SHA256.values(),
        *EXPECTED_RECEIPT_SEMANTIC_SHA256.values(),
        EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256,
        EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256,
    ]
    if not all(_hex64(value) for value in roots):
        return ["Item27 terminal evidence trust roots are not finalized"]
    _append(
        errors,
        evidence_path.is_file()
        and _sha256(evidence_path) == EXPECTED_EVIDENCE_FILE_SHA256,
        "Item27 evidence file bytes changed",
    )
    _append(
        errors,
        _semantic_sha256(payload) == EXPECTED_EVIDENCE_SEMANTIC_SHA256,
        "Item27 evidence semantics changed",
    )
    for action, receipt in receipts.items():
        path = root / RECEIPT_REFS[action]
        _append(
            errors,
            path.is_file()
            and _sha256(path) == EXPECTED_RECEIPT_FILE_SHA256[action],
            f"{action}: provider receipt file bytes changed",
        )
        _append(
            errors,
            _semantic_sha256(receipt)
            == EXPECTED_RECEIPT_SEMANTIC_SHA256[action],
            f"{action}: provider receipt semantics changed",
        )
    terminal_path = root / TERMINAL_CHECKPOINT_REF
    _append(
        errors,
        terminal_path.is_file()
        and _sha256(terminal_path) == EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256,
        "Item27 terminal checkpoint file bytes changed",
    )
    _append(
        errors,
        _semantic_sha256(terminal_checkpoint)
        == EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256,
        "Item27 terminal checkpoint semantics changed",
    )
    return errors


def validate_bundle(
    evidence_path: Path | None = None,
    *,
    root: Path = ROOT,
    expected_item26_terminal_acceptance_sha256: str | None = None,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    if not _hex64(expected_item26_terminal_acceptance_sha256):
        return ["Item26 terminal acceptance digest is required"]
    path = evidence_path or root / EVIDENCE_REF
    try:
        payload = load_evidence(path)
        receipts = _load_provider_receipts(root)
        terminal_checkpoint = _load_terminal_checkpoint(root)
        terminal_errors, _evidence_revision = _validate_terminal_checkpoint(
            terminal_checkpoint, payload, receipts, root=root
        )
        provider_projection = _provider_authority_projection(receipts)
        source = payload.get("source_binding")
        source_revision = (
            source.get("release_revision") if isinstance(source, dict) else ""
        )
        authority_errors, ci_authority = validate_authority_bundle(
            provider_projection, source_revision, root=root
        )
        ci_authority_errors: list[str] = []
        if ci_authority is not None:
            ci_authority_errors, _final_revision = (
                _validate_external_ci_authority(
                    ci_authority, payload, receipts, terminal_checkpoint,
                    root=root,
                )
            )
        return [
            *_validate_frozen_closure(
                path, payload, receipts, terminal_checkpoint, root=root
            ),
            *terminal_errors,
            *authority_errors,
            *ci_authority_errors,
            *validate_document(
                payload,
                root=root,
                receipt_payloads=receipts,
                expected_item26_terminal_acceptance_sha256=(
                    expected_item26_terminal_acceptance_sha256
                ),
                expected_readiness=expected_readiness,
            ),
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"cannot load Item27 evidence: {exc}"]


def validate_manifest_evidence(
    entries: Any,
    *,
    root: Path = ROOT,
    expected_item26_terminal_acceptance_sha256: str,
    expected_readiness: dict[str, Any],
) -> list[str]:
    """Bind the readiness ledger refs to the same evidence revision."""

    if not _hex64(expected_item26_terminal_acceptance_sha256):
        return ["Item26 terminal acceptance digest is required"]
    if not isinstance(entries, list) or not all(
        isinstance(item, dict)
        and set(item) == {"kind", "ref"}
        and item.get("kind") in {"git", "path"}
        and isinstance(item.get("ref"), str)
        and bool(item["ref"])
        for item in entries
    ):
        return ["Item27 manifest evidence fields mismatch"]
    try:
        payload = load_evidence(root / EVIDENCE_REF)
        terminal_checkpoint = _load_terminal_checkpoint(root)
        receipts = _load_provider_receipts(root)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"cannot load Item27 evidence: {exc}"]
    try:
        provider_projection = _provider_authority_projection(receipts)
    except (TypeError, ValueError) as exc:
        return [f"cannot project Item27 provider authority: {exc}"]
    authority_errors, ci_authority = validate_authority_bundle(
        provider_projection,
        (
            payload.get("source_binding", {}).get("release_revision")
            if isinstance(payload.get("source_binding"), dict) else ""
        ),
        root=root,
    )
    if authority_errors or ci_authority is None:
        return authority_errors or ["Item27 signed CI authority missing"]
    source = payload.get("source_binding")
    revision = source.get("release_revision") if isinstance(source, dict) else None
    evidence_revision = terminal_checkpoint.get("evidence_revision")
    expected_entries = {
        ("git", revision),
        ("git", evidence_revision),
        ("git", ci_authority.get("terminal_revision")),
        ("git", ci_authority.get("final_revision")),
        *[("path", ref) for ref in REQUIRED_MANIFEST_PATH_REFS],
    }
    actual_entries = [(item["kind"], item["ref"]) for item in entries]
    if (
        len(actual_entries) != len(expected_entries)
        or len(set(actual_entries)) != len(actual_entries)
        or set(actual_entries) != expected_entries
    ):
        return ["Item27 exact evidence refs required"]
    return validate_bundle(
        root=root,
        expected_item26_terminal_acceptance_sha256=(
            expected_item26_terminal_acceptance_sha256
        ),
        expected_readiness=expected_readiness,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            ROOT
            / "deploy"
            / "production"
            / "internal-deployment-readiness.json"
        ),
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        item26_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
            if control.get("id") == "backup_pitr_restore"
        ]
        if len(item26_controls) != 1:
            raise ValueError("exact Item26 control required")
        item26_entries = item26_controls[0].get("evidence")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print("internal_zero_provider_smoke_evidence=FAIL")
        print("- Item27 readiness manifest unavailable: " + str(exc))
        return 1
    item26_errors, item26_acceptance = validate_item26_terminal_evidence(
        item26_entries, root=ROOT
    )
    errors = item26_errors
    if not errors and item26_acceptance is not None:
        errors = validate_bundle(
            args.evidence,
            expected_item26_terminal_acceptance_sha256=item26_acceptance,
        )
    if errors:
        print("internal_zero_provider_smoke_evidence=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("internal_zero_provider_smoke_evidence=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
