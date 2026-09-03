#!/usr/bin/env python3
"""Verify the tracked Item 27 private zero-provider smoke evidence.

The original DoD requires one complete private, supplier-free operational
smoke of the current release. This verifier validates the four ordered
terminal Cloud Assistant projections and the shared executor-result contract.
It deliberately does not require a receipt, terminal checkpoint, external
signing authority, or retained raw provider bodies.
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

from validate_item27_internal_smoke_result_v1 import validate_executor_result


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-internal-zero-provider-smoke-verified-20260813.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
VERIFIER_REF = "tools/verify_internal_zero_provider_smoke_evidence.py"
EXECUTOR_REF = "deploy/production/internal_zero_provider_smoke.py"
RENDERER_REF = "tools/render_item27_internal_smoke_requests_v1.py"
VALIDATOR_REF = "tools/validate_item27_internal_smoke_result_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
EVIDENCE_SCHEMA = "noteai.item27.internal-zero-provider-smoke-evidence.v1"
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
CURRENT_RELEASE_REVISION = "c9b9ac423033f3c54cbe7ecf67cef63508934896"
API_C_EXECUTION_REVISION = "0d6caec647264d03026dcfa02d8d22ff268cdf24"
ITEM26_TERMINAL_ACCEPTANCE_SHA256 = (
    "4285231c59a111056426c643aac0764a1d7c32904caf46eacf555188d082a7b8"
)
ACTION_ROWS = (
    ("api_c", "api-c", API_C_EXECUTION_REVISION),
    ("api_f", "api-f", CURRENT_RELEASE_REVISION),
    ("worker_c", "worker-c", CURRENT_RELEASE_REVISION),
    ("worker_f", "worker-f", CURRENT_RELEASE_REVISION),
)
ACTION_ORDER = tuple(row[0] for row in ACTION_ROWS)
API_C_REUSE_CHANGED_PATHS = (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal_zero_provider_smoke.py",
    "tests/test_internal_zero_provider_smoke.py",
    "tests/test_render_item27_internal_smoke_requests_v1.py",
    "tools/render_item27_internal_smoke_requests_v1.py",
)
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF,
    VERIFIER_REF,
    EXECUTOR_REF,
    RENDERER_REF,
    VALIDATOR_REF,
}
REQUIRED_MANIFEST_GIT_REFS = {
    API_C_EXECUTION_REVISION,
    CURRENT_RELEASE_REVISION,
}
EXPECTED_PROVIDER_COMMITMENTS = {
    "api_c": {
        "command_name": "noteai-item27-internal-smoke-api-c-20260823-closure-fix1",
        "command_content_sha256": "c43119691bd5867cc4f33a47e9cb018009914bcc77153e0d354556c86c49c999",
        "executor_sha256": "cef5dc20d2bfdc079c655e0060d8faf83097112ad86f5802dda8a02caba9c99c",
        "provider_command_id_sha256": "ac3f277767dbfd68fb624ec6af7a4677476b70f14eae78559d7dab17be6c0a09",
        "provider_invoke_id_sha256": "5708db06127747c516ccdf1fc31bba9ddc9197a5f4853ed3a1324b2284706e1c",
        "target_identity_sha256": "c1b473b92b2c0b3703afdf4311f1ca4a2a69428844509aaa03d39ec32653926e",
        "provider_start_time_utc": "2026-08-23T13:25:42Z",
        "provider_finished_time_utc": "2026-08-23T13:26:27Z",
        "stdout_canonical_bytes": 1650,
        "stdout_canonical_sha256": "779e34d8b9dd1f5c37c0e4943e2e0544b4b09a67bb4c34f27b6927af98968b08",
        "terminal_readback_raw_sha256": {
            "commands": "a79ddeb6ce3cfcea5a065979a7c0dccff10312bea773a8e98484c94456efaa49",
            "invocations": "7518b3c8a16eaeca04fd373da3cb65d84738642f221073d19b9f4b1809984a6b",
            "results": "c8c5ca5fbe4498123075c4a9480338348beb3e3cf3f77d65f9b118aeea92503f",
        },
    },
    "api_f": {
        "command_name": "noteai-item27-internal-smoke-api-f-20260823-json-output-fix1",
        "command_content_sha256": "3bc53653d9e54a34a1e50e50e120df0115abd7d3643542b74694265c8794e521",
        "executor_sha256": "36e958b12251c1dcb528527dcd182f1ed80853797fa49fbbfcdfd1ef93675d38",
        "provider_command_id_sha256": "63b1a7f7a7dc3dc0c6ba5fca6f21213473c803cb1defba6a8ca0aa29e4587920",
        "provider_invoke_id_sha256": "d61fca63800654b86c093261ace63ada6683891c4e840ac672ed476a26ffb85e",
        "target_identity_sha256": "2c60d4bafae921961150894da54a7465cbfb9b9f6e8a8ed235e7dd07b50a7f4d",
        "provider_start_time_utc": "2026-08-23T15:06:46Z",
        "provider_finished_time_utc": "2026-08-23T15:08:06Z",
        "stdout_canonical_bytes": 1466,
        "stdout_canonical_sha256": "9f2c20e42276bb80162f6bd36eed0ab8b0c249e649f4f1b16e4b73f90786581c",
        "terminal_readback_raw_sha256": {
            "commands": "55207c98e093e9687b017bf65639c3c64a94eefb4dfc53792baaf04c5b10f22d",
            "invocations": "9ce26df72f6ba0c726d4d381d4597f75c3aa5dcbf592a1b0207345fb61339bb1",
            "results": "b1bcbf6db3a7a50f8b9a7097579e6cbdf6054a44f069c3d3bd72fa56a7885d05",
        },
    },
    "worker_c": {
        "command_name": "noteai-item27-internal-smoke-worker-c-20260813-v1",
        "command_content_sha256": "83684d4e99bc9b8e520b0ff6ebd2df935a7f07e37226a2c8ed672a1aa3e0e97c",
        "executor_sha256": "36e958b12251c1dcb528527dcd182f1ed80853797fa49fbbfcdfd1ef93675d38",
        "provider_command_id_sha256": "cbf524e14f74b74c890e7b441f99ac2fe608c90d27e12426dbd242ada09bef3c",
        "provider_invoke_id_sha256": "976bf8840d290b49cf7cd9f6fa213f961f3535a14123f6375c70a7cf274b66f8",
        "target_identity_sha256": "9df8cee339ab8cb82cef0a62729709a557975e0d471104de516e5872a17af6ba",
        "provider_start_time_utc": "2026-08-23T15:08:26Z",
        "provider_finished_time_utc": "2026-08-23T15:09:04Z",
        "stdout_canonical_bytes": 801,
        "stdout_canonical_sha256": "31dbd37310676b10b63f9e5a662cf544cde41a1f03739cd57f2537cdc85454e4",
        "terminal_readback_raw_sha256": {
            "commands": "704f94ee9480f2a725c7c679601b554a735b0ea83a9b7b4790462979e2292f89",
            "invocations": "2130223d1fe26a84997a633dc76a90179c435427fc0554b074df4a16b9975d4d",
            "results": "b477eda34a449c0611cba9392afa809ee858ad447f2abc878c3e7bbb4bc29077",
        },
    },
    "worker_f": {
        "command_name": "noteai-item27-internal-smoke-worker-f-20260813-v1",
        "command_content_sha256": "d01f6c7e200b4c3df52887f0ef348d8c6216af662001afdd15ea8f145df8c86e",
        "executor_sha256": "36e958b12251c1dcb528527dcd182f1ed80853797fa49fbbfcdfd1ef93675d38",
        "provider_command_id_sha256": "15006d4931723220e4e158a523e210ac5208970bcd3d96cd18d4276bc006d49f",
        "provider_invoke_id_sha256": "85b55bace55eae984ae06ae0aae7eff55a77d52d88a3ea146fcb35decd0529f2",
        "target_identity_sha256": "4fc521680ad0154fc1f14f9ba30daf7d231afe1816c909513d8d4ab70c2db87f",
        "provider_start_time_utc": "2026-08-23T15:09:45Z",
        "provider_finished_time_utc": "2026-08-23T15:10:25Z",
        "stdout_canonical_bytes": 801,
        "stdout_canonical_sha256": "c236da07310f2376f0c2ad7f14bf541b59f063f8f7338fa67f103ef37b8508e4",
        "terminal_readback_raw_sha256": {
            "commands": "2350b5cfe58b8d912904ec41a10b05dc8c2f4e717f3a72acf98bf77acf323397",
            "invocations": "8419e48d3b539a8c1a8d89ac0b383a0eff8ff6d058c879e4a3fa56cced040887",
            "results": "8026273c49c374820e20b144fbb5e96d4df83059517c4e58d8d31822986e94c0",
        },
    },
}
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

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_EVIDENCE_BYTES = 512 * 1024
TOP_LEVEL_KEYS = {
    "schema_version", "schema", "task_id", "status", "observed_at_utc",
    "source_binding", "invocations", "aggregate", "final_runtime_state",
    "mutation_counters", "cost_and_data_boundary", "capture_recovery",
    "readiness", "terminal_acceptance_sha256",
}
INVOCATION_KEYS = {
    "ordinal", "action", "mode", "source_revision",
    "provider_terminal_status", "provider_result_status",
    "provider_command_count", "provider_invocation_count",
    "provider_result_count", "exit_code", "dropped_count", "repeat_count",
    "automatic_retry_count", "same_invocation_replay_allowed",
    *next(iter(EXPECTED_PROVIDER_COMMITMENTS.values())).keys(),
    "result",
}


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


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


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or UTC.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )


def _git_commit_exists(revision: Any, *, root: Path) -> bool:
    if type(revision) is not str or HEX40.fullmatch(revision) is None:
        return False
    return _run_git(root, "cat-file", "-e", f"{revision}^{{commit}}").returncode == 0


def _git_is_ancestor(ancestor: str, descendant: str, *, root: Path) -> bool:
    return _run_git(
        root, "merge-base", "--is-ancestor", ancestor, descendant
    ).returncode == 0


def _git_file_sha256(revision: str, ref: str, *, root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{ref}"], cwd=root, check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return _sha256_bytes(completed.stdout)


def _git_changed_paths(before: str, after: str, *, root: Path) -> list[str] | None:
    completed = _run_git(root, "diff", "--name-only", f"{before}..{after}")
    if completed.returncode != 0:
        return None
    return [line for line in completed.stdout.splitlines() if line]


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
    if type(payload) is not dict:
        raise ValueError("evidence root must be an object")
    return payload


def terminal_acceptance_sha256(payload: dict[str, Any]) -> str:
    projection = {
        key: value for key, value in payload.items()
        if key != "terminal_acceptance_sha256"
    }
    return _sha256_bytes(_canonical_bytes(projection))


def _derived_aggregate(invocations: list[dict[str, Any]]) -> dict[str, int]:
    results = [item["result"] for item in invocations]
    return {
        "command_count": sum(item["provider_command_count"] for item in invocations),
        "invocation_count": sum(item["provider_invocation_count"] for item in invocations),
        "terminal_result_count": sum(item["provider_result_count"] for item in invocations),
        "pass_count": sum(result["status"] == "PASS" for result in results),
        "loopback_endpoint_count": sum(result["loopback_endpoint_count"] for result in results),
        "role_count": sum(len(result["roles"]) for result in results),
        "service_start_count": sum(result["service_start_count"] for result in results),
        "service_stop_count": sum(result["service_stop_count"] for result in results),
        "provider_call_count": sum(result["provider_call_count"] for result in results),
        "provider_attempt_count": sum(result["provider_attempt_count"] for result in results),
        "oss_mutation_count": sum(result["oss_mutation_count"] for result in results),
        "production_database_mutation_count": sum(result["production_database_mutation_count"] for result in results),
        "synthetic_record_count": sum(result["synthetic_record_count"] for result in results),
        "public_request_count": sum(result["public_request_count"] for result in results),
        "public_listener_count": sum(result["public_listener_count"] for result in results),
        "automatic_retry_count": sum(item["automatic_retry_count"] for item in invocations),
    }


def validate_document(
    payload: dict[str, Any], *, root: Path = ROOT,
    expected_item26_terminal_acceptance_sha256: str | None = None,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if type(payload) is not dict:
        return ["evidence root must be an object"]
    _append(errors, set(payload) == TOP_LEVEL_KEYS, "top-level fields mismatch")
    _append(errors, payload.get("schema_version") == 1, "schema version mismatch")
    _append(errors, payload.get("schema") == EVIDENCE_SCHEMA, "schema mismatch")
    _append(errors, payload.get("task_id") == TASK_ID, "task id mismatch")
    _append(errors, payload.get("status") == "VERIFIED_CLEAN", "status mismatch")
    observed = _utc(payload.get("observed_at_utc"))
    _append(errors, observed is not None, "UTC observation timestamp required")

    source = payload.get("source_binding")
    source_keys = {
        "branch", "current_release_revision",
        "item26_terminal_acceptance_sha256", "executor_ref", "renderer_ref",
        "validator_ref", "action_order", "api_c_reused_without_rerun",
        "api_c_execution_revision", "api_c_reuse_changed_paths",
    }
    if type(source) is not dict or set(source) != source_keys:
        errors.append("source binding fields mismatch")
    else:
        expected_item26 = (
            expected_item26_terminal_acceptance_sha256
            or ITEM26_TERMINAL_ACCEPTANCE_SHA256
        )
        _append(errors, source == {
            "branch": SOURCE_BRANCH,
            "current_release_revision": CURRENT_RELEASE_REVISION,
            "item26_terminal_acceptance_sha256": expected_item26,
            "executor_ref": EXECUTOR_REF,
            "renderer_ref": RENDERER_REF,
            "validator_ref": VALIDATOR_REF,
            "action_order": list(ACTION_ORDER),
            "api_c_reused_without_rerun": True,
            "api_c_execution_revision": API_C_EXECUTION_REVISION,
            "api_c_reuse_changed_paths": list(API_C_REUSE_CHANGED_PATHS),
        }, "source binding mismatch")
        _append(
            errors,
            _git_commit_exists(API_C_EXECUTION_REVISION, root=root)
            and _git_commit_exists(CURRENT_RELEASE_REVISION, root=root)
            and _git_is_ancestor(
                API_C_EXECUTION_REVISION, CURRENT_RELEASE_REVISION, root=root
            )
            and _git_is_ancestor(CURRENT_RELEASE_REVISION, "HEAD", root=root),
            "source revision ancestry mismatch",
        )
        _append(
            errors,
            _git_changed_paths(
                API_C_EXECUTION_REVISION, CURRENT_RELEASE_REVISION, root=root
            ) == list(API_C_REUSE_CHANGED_PATHS),
            "API-C reuse scope mismatch",
        )

    invocations = payload.get("invocations")
    derived_rows: list[dict[str, Any]] = []
    previous_finished: datetime | None = None
    if type(invocations) is not list or len(invocations) != len(ACTION_ROWS):
        errors.append("invocation count mismatch")
    else:
        for ordinal, (invocation, (action, mode, revision)) in enumerate(
            zip(invocations, ACTION_ROWS), 1
        ):
            if type(invocation) is not dict or set(invocation) != INVOCATION_KEYS:
                errors.append(f"{action}: invocation fields mismatch")
                continue
            expected_provider = EXPECTED_PROVIDER_COMMITMENTS[action]
            _append(
                errors,
                invocation.get("ordinal") == ordinal
                and invocation.get("action") == action
                and invocation.get("mode") == mode
                and invocation.get("source_revision") == revision,
                f"{action}: invocation identity mismatch",
            )
            _append(
                errors,
                all(
                    _strict_equal(invocation.get(key), value)
                    for key, value in expected_provider.items()
                ),
                f"{action}: provider commitment mismatch",
            )
            _append(
                errors,
                invocation.get("provider_terminal_status") == "Finished"
                and invocation.get("provider_result_status") == "Success"
                and invocation.get("provider_command_count") == 1
                and invocation.get("provider_invocation_count") == 1
                and invocation.get("provider_result_count") == 1
                and invocation.get("exit_code") == 0
                and invocation.get("dropped_count") == 0
                and invocation.get("repeat_count") == 1
                and invocation.get("automatic_retry_count") == 0
                and invocation.get("same_invocation_replay_allowed") is False,
                f"{action}: terminal execution mismatch",
            )
            _append(
                errors,
                _git_file_sha256(revision, EXECUTOR_REF, root=root)
                == invocation.get("executor_sha256"),
                f"{action}: executor revision binding mismatch",
            )
            result_errors, projection = validate_executor_result(
                invocation.get("result"), action
            )
            errors.extend(result_errors)
            derived_rows.append(projection)
            start = _utc(invocation.get("provider_start_time_utc"))
            finished = _utc(invocation.get("provider_finished_time_utc"))
            _append(
                errors,
                start is not None and finished is not None and start < finished
                and (previous_finished is None or previous_finished < start)
                and (observed is None or finished < observed),
                f"{action}: provider terminal timestamps are not strictly ordered",
            )
            previous_finished = finished

    if len(derived_rows) >= 2:
        _append(
            errors,
            derived_rows[0].get("hash:/legal/contracts")
            == derived_rows[1].get("hash:/legal/contracts")
            and derived_rows[0].get("hash:/billing/tiers")
            == derived_rows[1].get("hash:/billing/tiers"),
            "API-C/API-F contract projection parity mismatch",
        )
    if type(invocations) is list and all(
        type(item) is dict and "result" in item for item in invocations
    ):
        _append(
            errors,
            _strict_equal(payload.get("aggregate"), _derived_aggregate(invocations)),
            "aggregate mismatch",
        )

    _append(errors, _strict_equal(payload.get("final_runtime_state"), {
        "builder": {"state": "Stopped", "billing": "StopCharging"},
        "worker_c": {"state": "Stopped", "billing": "StopCharging"},
        "worker_f": {"state": "Stopped", "billing": "StopCharging"},
        "temporary_compute_running_count": 0,
        "temporary_security_group_rule_count": 0,
        "temporary_peering_count": 0,
        "temporary_route_count": 0,
        "temporary_tls_listener_count": 0,
        "original_state_restored": True,
        "new_public_listener_count": 0,
    }), "final runtime state mismatch")
    _append(errors, _strict_equal(payload.get("mutation_counters"), {
        "production_database_mutation_count": 0,
        "provider_attempt_count": 0,
        "provider_call_count": 0,
        "oss_mutation_count": 0,
        "synthetic_record_count": 0,
        "public_request_count": 0,
    }), "mutation counters mismatch")
    _append(errors, _strict_equal(payload.get("cost_and_data_boundary"), {
        "paid_resource_create_count": 0,
        "final_continuation_worker_compute_seconds": 152,
        "worker_unit_hourly_rate_cny": "0.8164",
        "final_continuation_estimated_compute_cost_cny": "0.034470",
        "item27_total_actual_cost_cny": None,
        "billing_status": "PENDING_PROVIDER_SETTLEMENT",
        "real_supplier_call_count": 0,
        "production_business_row_write_count": 0,
        "public_traffic_change_count": 0,
    }), "cost/data boundary mismatch")
    _append(errors, _strict_equal(payload.get("capture_recovery"), {
        "cloudshell_expired_after_final_pass": True,
        "byte_identical_new_receipts_recoverable": False,
        "fabricated_receipt_count": 0,
        "terminal_history_reread": True,
        "terminal_readback_archive_repo_out": True,
        "terminal_readback_archive_bytes": 29586,
        "terminal_readback_archive_sha256": "9186c5facaec91a40cf30727416d00adc33f3a1f4fe0c7be3097fd67ca942a99",
        "terminal_readback_raw_file_count": 10,
        "final_compute_readback_sha256": "29631c0eb4c3dd992e622f9fe609cb56feb0415b8e8ae0635878c52a5880f555",
        "secret_value_count": 0,
    }), "capture recovery disclosure mismatch")
    _append(
        errors,
        _strict_equal(payload.get("readiness"), expected_readiness or DEFAULT_READINESS),
        "readiness transition mismatch",
    )
    acceptance = payload.get("terminal_acceptance_sha256")
    _append(
        errors,
        type(acceptance) is str and HEX64.fullmatch(acceptance) is not None
        and acceptance == terminal_acceptance_sha256(payload),
        "terminal acceptance digest mismatch",
    )
    return errors


def validate_bundle(
    evidence_path: Path | None = None, *, root: Path = ROOT,
    expected_item26_terminal_acceptance_sha256: str | None = None,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    expected_item26 = (
        expected_item26_terminal_acceptance_sha256
        or ITEM26_TERMINAL_ACCEPTANCE_SHA256
    )
    if type(expected_item26) is not str or HEX64.fullmatch(expected_item26) is None:
        return ["Item26 terminal acceptance digest is required"]
    try:
        payload = load_evidence(evidence_path or root / EVIDENCE_REF)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"cannot load Item27 evidence: {exc}"]
    return validate_document(
        payload, root=root,
        expected_item26_terminal_acceptance_sha256=expected_item26,
        expected_readiness=expected_readiness,
    )


def validate_manifest_evidence(
    entries: Any, *, root: Path = ROOT,
    expected_item26_terminal_acceptance_sha256: str,
    expected_readiness: dict[str, Any],
) -> list[str]:
    """Bind the readiness row to the exact original-DoD evidence set."""

    if type(expected_item26_terminal_acceptance_sha256) is not str or HEX64.fullmatch(
        expected_item26_terminal_acceptance_sha256
    ) is None:
        return ["Item26 terminal acceptance digest is required"]
    if type(entries) is not list or any(
        type(item) is not dict or set(item) != {"kind", "ref"}
        or item.get("kind") not in {"git", "path"}
        or type(item.get("ref")) is not str or not item["ref"]
        for item in entries
    ):
        return ["Item27 manifest evidence fields mismatch"]
    actual = [(item["kind"], item["ref"]) for item in entries]
    expected = {
        *[("path", ref) for ref in REQUIRED_MANIFEST_PATH_REFS],
        *[("git", ref) for ref in REQUIRED_MANIFEST_GIT_REFS],
    }
    if (
        len(actual) != len(expected) or len(set(actual)) != len(actual)
        or set(actual) != expected
    ):
        return ["Item27 exact original-DoD evidence refs required"]
    return validate_bundle(
        root=root,
        expected_item26_terminal_acceptance_sha256=(
            expected_item26_terminal_acceptance_sha256
        ),
        expected_readiness=expected_readiness,
    )


def _control(manifest: dict[str, Any], control_id: str) -> dict[str, Any] | None:
    for layer in manifest.get("layers", []):
        for control in layer.get("controls", []):
            if control.get("id") == control_id:
                return control
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "deploy" / "production" / "internal-deployment-readiness.json",
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        item26 = _control(manifest, "backup_pitr_restore")
        item27 = _control(manifest, "internal_zero_provider_smoke")
        if item26 is None or item27 is None:
            raise ValueError("Item26/Item27 readiness rows missing")
        # Imported here to avoid the gate -> Item27 verifier import cycle while
        # still sharing the gate's original-DoD Item26 semantic validator.
        from internal_deployment_readiness_gate import (  # noqa: PLC0415
            validate_item26_terminal_evidence,
        )

        item26_errors, item26_acceptance = validate_item26_terminal_evidence(
            item26, root=ROOT
        )
        if item26_errors or item26_acceptance is None:
            errors = item26_errors or ["Item26 terminal acceptance missing"]
        elif args.evidence != EVIDENCE_PATH:
            errors = validate_bundle(
                args.evidence,
                expected_item26_terminal_acceptance_sha256=item26_acceptance,
            )
        else:
            errors = validate_manifest_evidence(
                item27.get("evidence"),
                expected_item26_terminal_acceptance_sha256=item26_acceptance,
                expected_readiness=DEFAULT_READINESS,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors = [f"cannot verify Item27 evidence: {exc}"]
    if errors:
        print("internal_zero_provider_smoke_evidence=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("internal_zero_provider_smoke_evidence=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
