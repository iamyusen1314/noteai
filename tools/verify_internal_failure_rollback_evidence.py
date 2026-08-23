#!/usr/bin/env python3
"""Verify the single tracked Item 28 reconciled rollback evidence.

The production executor ended UNKNOWN while systemd was in its automatic-
restart transition. The original DoD is therefore accepted only when that
UNKNOWN result, the independent same-release readback, and exact cleanup PASS
all agree. No receipt, checkpoint, raw archive, or external authority applies.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_internal_failure_rollback_evidence.py"
EXECUTOR_REF = "deploy/production/internal_failure_rollback.py"
RENDERER_REF = "tools/render_item28_internal_failure_rollback_request_v1.py"
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-internal-failure-rollback-verified-20260814.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
EVIDENCE_SCHEMA = "noteai.item28.internal-failure-rollback-evidence.v1"
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
CURRENT_RELEASE_REVISION = "c9b9ac423033f3c54cbe7ecf67cef63508934896"
INITIAL_PREFLIGHT_REVISION = "5b856a4b90ceca960754d21e95492a23ae33e08c"
EXECUTION_SOURCE_REVISION = "40d8fa29ebf1dcb9af8f475528a94e1cf8322874"
EXECUTED_EXECUTOR_SHA256 = (
    "2c37bb2b79df4260fba7624091fd245e3543647d4db9eecf525492b560675ca7"
)
EXECUTED_RENDERER_SHA256 = (
    "df81e4e52ed1b23f92665c6e9980b3b0c328b8e211777bb7dcb894fd5e28686c"
)
UNIT_SHA256 = "f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936"
DROPIN_SHA256 = "d9fc435118b567a4ef1ea28ab25d7358f0f98e77f83c52e04514b4cb44433305"
RELEASE_SHA256 = "20fae7fd4f585966706736fcac3da2198c7d175cbb8f099cf792bf3fa2b22066"
PREDECESSOR_ACCEPTANCES = {
    "item25": "e456faeea90f4139068cefce7486af863a86b52f8f160f951a007955531ffdb6",
    "item26": "4285231c59a111056426c643aac0764a1d7c32904caf46eacf555188d082a7b8",
    "item27": "a42a6fe6bd0aebfb6856fac9ea01da1043a054e67c9fae3987b8608e3342a077",
}
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF, VERIFIER_REF, EXECUTOR_REF, RENDERER_REF,
}
REQUIRED_MANIFEST_GIT_REFS = {EXECUTION_SOURCE_REVISION}
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

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_EVIDENCE_BYTES = 256 * 1024
TOP_LEVEL_KEYS = {
    "schema_version", "schema", "task_id", "status", "observed_at_utc",
    "source_binding", "nonmutating_precursors", "rehearsal",
    "reconciliation", "cleanup", "final_runtime_state",
    "mutation_counters", "cost_and_data_boundary", "readiness",
    "terminal_acceptance_sha256",
}
HEALTH = [
    {"path": "/health/live", "status": 200, "state": "ok"},
    {"path": "/health/ready", "status": 200, "state": "ready"},
]


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def load_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
        raise ValueError("evidence size/encoding invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if type(value) is not dict:
        raise ValueError("evidence root must be an object")
    return value


def terminal_acceptance_sha256(value: dict[str, Any]) -> str:
    projection = {
        key: item for key, item in value.items()
        if key != "terminal_acceptance_sha256"
    }
    return _sha(_canonical(projection))


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or UTC.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _git(*args: str, root: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True,
    )


def _git_commit_exists(revision: str, *, root: Path) -> bool:
    return (
        HEX40.fullmatch(revision) is not None
        and _git(
            "cat-file", "-e", revision + "^{commit}", root=root
        ).returncode == 0
    )


def _git_is_ancestor(before: str, after: str, *, root: Path) -> bool:
    return _git(
        "merge-base", "--is-ancestor", before, after, root=root
    ).returncode == 0


def _git_file_sha256(revision: str, ref: str, *, root: Path) -> str | None:
    result = _git("show", revision + ":" + ref, root=root)
    return _sha(result.stdout) if result.returncode == 0 else None


def _expected_initial_precursor() -> dict[str, Any]:
    return {
        "kind": "initial_rehearsal_preflight",
        "command_name": "noteai-item28-internal-rollback-api-f-20260814-v1",
        "source_revision": INITIAL_PREFLIGHT_REVISION,
        "request_canonical_sha256": "cec59f251a2d3583ab0c4966a30d7b0c8ad55557039290b490a8760bcbc1862e",
        "command_wrapper_bytes": 13085,
        "command_wrapper_sha256": "fb99300b9808d8e2ccf8665fa96f92586df0fab23e19a6cd430a46babf05bf8b",
        "executor_sha256": "5f233668966bef323d036393ab21a0f1f67d3e935a38e766e857a4110dcb5499",
        "provider_command_id_sha256": "d276f1f4557770b39d77e2fedce5ac946ec27a3c8edf4b3e8ed9b8749650e1a4",
        "provider_invoke_id_sha256": "880a9cec4afa8a84b017fa04c552893d3427ca54100bea5bed1b623ad9a7ebfb",
        "provider_invocation_status": "Failed",
        "provider_instance_status": "Finished",
        "provider_start_time_utc": "2026-08-23T17:25:36Z",
        "provider_finished_time_utc": "2026-08-23T17:25:36Z",
        "exit_code": 3, "dropped_count": 0, "repeat_count": 1,
        "stdout_bytes": 321,
        "stdout_sha256": "732801e17e4ed29d1bfed81f555f32cbd8933e2d46cf0408d8885fff6bcdc35d",
        "result": {
            "automatic_retry_allowed": False, "code": "file_identity",
            "mode": "api-f", "restart_attempt_count": 0,
            "rollback_requested": False,
            "runtime_mutation_attempted": False,
            "same_invocation_replay_allowed": False,
            "schema": "noteai.item28.internal-failure-rollback.v1",
            "status": "FAIL", "task_id": TASK_ID,
        },
    }


def _expected_cleanup_precursor() -> dict[str, Any]:
    return {
        "kind": "cleanup_precondition",
        "command_name": "noteai-item28-api-f-owned-residue-cleanup-20260824-v1",
        "provider_command_id_sha256": "6474447f27b640b474053ba11d07a3bcb8fb7c7dc4f1925cb4d1eb7b6670f36e",
        "provider_invoke_id_sha256": "412674533dfde98899ef2023b7344a48b74414ab8a238282836b9a8e953f86ea",
        "provider_invocation_status": "Failed",
        "provider_instance_status": "Finished",
        "provider_start_time_utc": "2026-08-23T18:04:43Z",
        "provider_finished_time_utc": "2026-08-23T18:04:44Z",
        "exit_code": 1, "dropped_count": 0, "repeat_count": 1,
        "stdout_bytes": 97,
        "stdout_sha256": "be64eda3eef962f15f06b829d12aa6f016c6a385ce2eff743ad95617c6bece11",
        "failure_code": "guardian_precondition",
        "owned_file_delete_count": 0, "task_root_delete_count": 0,
        "service_mutation_count": 0,
        "same_invocation_replay_allowed": False,
    }


def _expected_rehearsal() -> dict[str, Any]:
    return {
        "command_name": "noteai-item28-internal-rollback-api-f-20260824-unit-fix1",
        "source_revision": EXECUTION_SOURCE_REVISION,
        "request_canonical_bytes": 17953,
        "request_canonical_sha256": "5694bb99b1fdeac20a0b674f807d5d0124b4d4567d7640b662e31f67ab488994",
        "command_wrapper_bytes": 13089,
        "command_wrapper_sha256": "f6883cd6be703c397da4c6f45bd28210100d2a073a8e907a70c17e984cc625a6",
        "executor_sha256": EXECUTED_EXECUTOR_SHA256,
        "client_token_sha256": "345acc25b069e4215e0d211bba99cdb36247e86e022ba7d7f38e9169c3270d12",
        "pre_dispatch_command_history_count": 0,
        "pre_dispatch_invocation_history_count": 0,
        "dispatch_count": 1,
        "provider_command_id_sha256": "867bee66e785eab7fadd1271169b7f75d1da2ad11788eaac37095fa0cf4ea35c",
        "provider_invoke_id_sha256": "7ffcb6ad47f41c8b773e750afc12457232f7d559036f42a3eaa6552cbd96feda",
        "provider_invocation_status": "Failed",
        "provider_instance_status": "Finished",
        "provider_start_time_utc": "2026-08-23T17:53:46Z",
        "provider_finished_time_utc": "2026-08-23T17:53:56Z",
        "exit_code": 4, "dropped_count": 0, "repeat_count": 1,
        "stdout_bytes": 319,
        "stdout_sha256": "5e721bc8ac2997592fa85b284aff0bd27df237e3224b8bd54f0fa6ec6c4251995",
        "automatic_retry_count": 0,
        "same_invocation_replay_allowed": False,
        "result": {
            "automatic_retry_allowed": False, "code": "unit_state",
            "mode": "api-f", "restart_attempt_count": 1,
            "rollback_requested": True, "runtime_mutation_attempted": True,
            "same_invocation_replay_allowed": False,
            "schema": "noteai.item28.internal-failure-rollback.v1",
            "status": "UNKNOWN", "task_id": TASK_ID,
        },
    }


def _expected_reconciliation() -> dict[str, Any]:
    health = [dict(row, service="noteai-api") for row in HEALTH]
    return {
        "command_name": "noteai-item28-api-f-post-unknown-readback-20260824-v1",
        "provider_command_id_sha256": "20534b2ef3215fe4a6a5db5291f4dc08ec661d25950a80cef2e3ce44de328575",
        "provider_invoke_id_sha256": "73f732bfe34ff4ab4b61a3531d5b8745260b111d7f1671a86109682485b8892c",
        "provider_invocation_status": "Success",
        "provider_instance_status": "Finished",
        "provider_start_time_utc": "2026-08-23T17:59:22Z",
        "provider_finished_time_utc": "2026-08-23T17:59:22Z",
        "exit_code": 0, "dropped_count": 0, "repeat_count": 1,
        "stdout_bytes": 1643,
        "stdout_sha256": "bdf59584db9ad81ce524b89cb954d96c43d67c7e0233dcf6b9a4847e2ae19305",
        "guardian_result": {
            "schema": "noteai.item28.guardian-result.v1",
            "status": "RESTORED", "dropin_removed": True,
            "staged_cleanup_status": "ABSENT", "staged_residue_count": 0,
            "daemon_reload_count": 1, "runtime_start_count": 0,
            "volatile_residue_count": 0,
        },
        "systemd": {
            "load_state": "loaded", "active_state": "active",
            "sub_state": "running", "result": "success", "nrestarts": 1,
            "enabled": True, "dropin_path_count": 0,
            "need_daemon_reload": False,
        },
        "unit": {
            "mode": 420, "uid": 0, "gid": 0, "link_count": 1,
            "bytes": 1510, "sha256": UNIT_SHA256,
        },
        "container": {
            "count": 1,
            "image_id": "sha256:dd955f9e736fc00df471f39de6e483ed0873f5855cc0fffcc074823845fefd53",
            "image_ref": "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:612a7e57b8a4226e4c23b02607ee60fb796f7cae9eb46ea1843aed11fc517620",
            "user": "999:999", "readonly_rootfs": True, "running": True,
            "loopback_binding": "8000/tcp -> 127.0.0.1:8000",
            "public_listener_count": 0,
        },
        "health": health, "task_root_present_before_cleanup": True,
        "volatile_residue_count": 0, "original_release_restored": True,
    }


def _expected_cleanup() -> dict[str, Any]:
    return {
        "command_name": "noteai-item28-api-f-owned-residue-cleanup-20260824-runtime0-fix1",
        "provider_command_id_sha256": "8d5539455ae90a0b5831d5da3e65ad34ddb34296b3007cb5e952cd6f2b32e6e3",
        "provider_invoke_id_sha256": "b26b946c08bd6d7742c23999954c1d9908dfd13872e544eef41f554e6e7b91ce",
        "provider_invocation_status": "Success",
        "provider_instance_status": "Finished",
        "provider_start_time_utc": "2026-08-23T18:10:57Z",
        "provider_finished_time_utc": "2026-08-23T18:10:58Z",
        "exit_code": 0, "dropped_count": 0, "repeat_count": 1,
        "stdout_bytes": 914,
        "stdout_sha256": "15bb339a37586a08587fc6e6325518d5e2938bec143cd73801aa765fc531ea8d",
        "result": {
            "guardian_runtime_start_count": 0,
            "guardian_status": "RESTORED", "iam_mutation_count": 0,
            "managed_systemd_restart_count": 1, "oss_mutation_count": 0,
            "owned_file_delete_count": 5, "post_health": HEALTH,
            "pre_health": HEALTH, "production_database_mutation_count": 0,
            "provider_call_count": 0, "public_request_count": 0,
            "release_identity_sha256": RELEASE_SHA256,
            "release_identity_unchanged": True, "runtime_restart_count": 0,
            "schema": "noteai.item28.owned-residue-cleanup.v1",
            "status": "PASS", "task_id": TASK_ID,
            "task_root_delete_count": 1,
            "unit_fragment_sha256": UNIT_SHA256,
            "volatile_residue_count": 0,
        },
    }


def validate_document(
    value: Any, *, root: Path = ROOT,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if type(value) is not dict:
        return ["evidence root must be an object"]
    _append(errors, set(value) == TOP_LEVEL_KEYS, "top-level fields mismatch")
    _append(errors, value.get("schema_version") == 1, "schema version mismatch")
    _append(errors, value.get("schema") == EVIDENCE_SCHEMA, "schema mismatch")
    _append(errors, value.get("task_id") == TASK_ID, "task id mismatch")
    _append(
        errors, value.get("status") == "VERIFIED_RECONCILED",
        "status mismatch",
    )
    _append(
        errors,
        value.get("observed_at_utc") == "2026-08-23T18:10:58Z"
        and _utc(value.get("observed_at_utc")) is not None,
        "observation timestamp mismatch",
    )

    expected_source = {
        "branch": SOURCE_BRANCH,
        "current_release_revision": CURRENT_RELEASE_REVISION,
        "initial_preflight_revision": INITIAL_PREFLIGHT_REVISION,
        "execution_source_revision": EXECUTION_SOURCE_REVISION,
        "executor_ref": EXECUTOR_REF, "renderer_ref": RENDERER_REF,
        "verifier_ref": VERIFIER_REF, "executed_executor_bytes": 41841,
        "executed_executor_sha256": EXECUTED_EXECUTOR_SHA256,
        "executed_renderer_sha256": EXECUTED_RENDERER_SHA256,
        "target_identity_sha256": "2c60d4bafae921961150894da54a7465cbfb9b9f6e8a8ed235e7dd07b50a7f4d",
        "unit_fragment_sha256": UNIT_SHA256,
        "volatile_dropin_sha256": DROPIN_SHA256,
        "release_identity_sha256": RELEASE_SHA256,
        "predecessor_acceptances": PREDECESSOR_ACCEPTANCES,
    }
    _append(
        errors, _strict(value.get("source_binding"), expected_source),
        "source binding mismatch",
    )
    _append(
        errors,
        all(_git_commit_exists(revision, root=root) for revision in (
            CURRENT_RELEASE_REVISION, INITIAL_PREFLIGHT_REVISION,
            EXECUTION_SOURCE_REVISION,
        ))
        and _git_is_ancestor(
            CURRENT_RELEASE_REVISION, INITIAL_PREFLIGHT_REVISION, root=root
        )
        and _git_is_ancestor(
            INITIAL_PREFLIGHT_REVISION, EXECUTION_SOURCE_REVISION, root=root
        )
        and _git_is_ancestor(EXECUTION_SOURCE_REVISION, "HEAD", root=root),
        "source revision ancestry mismatch",
    )
    _append(
        errors,
        _git_file_sha256(
            EXECUTION_SOURCE_REVISION, EXECUTOR_REF, root=root
        ) == EXECUTED_EXECUTOR_SHA256
        and _git_file_sha256(
            EXECUTION_SOURCE_REVISION, RENDERER_REF, root=root
        ) == EXECUTED_RENDERER_SHA256,
        "executed source bytes mismatch",
    )

    _append(
        errors,
        _strict(value.get("nonmutating_precursors"), [
            _expected_initial_precursor(), _expected_cleanup_precursor(),
        ]),
        "nonmutating precursor history mismatch",
    )
    _append(
        errors, _strict(value.get("rehearsal"), _expected_rehearsal()),
        "rehearsal history mismatch",
    )
    _append(
        errors,
        _strict(value.get("reconciliation"), _expected_reconciliation()),
        "runtime reconciliation mismatch",
    )
    _append(
        errors, _strict(value.get("cleanup"), _expected_cleanup()),
        "cleanup mismatch",
    )

    expected_final = {
        "api_c": {"state": "Running", "billing": "PrePaid"},
        "api_f": {"state": "Running", "billing": "PrePaid"},
        "builder": {"state": "Stopped", "billing": "StopCharging"},
        "worker_c": {"state": "Stopped", "billing": "StopCharging"},
        "worker_f": {"state": "Stopped", "billing": "StopCharging"},
        "temporary_compute_running_count": 0,
        "api_f_active": True, "api_f_enabled": True,
        "api_f_loopback_live_ready": True, "public_listener_count": 0,
        "volatile_dropin_residue_count": 0, "task_root_residue_count": 0,
        "original_release_restored": True,
    }
    _append(
        errors, _strict(value.get("final_runtime_state"), expected_final),
        "final runtime state mismatch",
    )
    expected_counters = {
        "host_fault_injection_count": 1,
        "managed_restart_attempt_count": 1,
        "managed_systemd_restart_count": 1,
        "guardian_rollback_count": 1,
        "guardian_runtime_start_count": 0,
        "cleanup_runtime_restart_count": 0,
        "provider_call_count": 0, "provider_attempt_count": 0,
        "oss_mutation_count": 0, "iam_mutation_count": 0,
        "production_database_mutation_count": 0,
        "cloud_resource_create_count": 0, "public_request_count": 0,
    }
    _append(
        errors, _strict(value.get("mutation_counters"), expected_counters),
        "mutation counters mismatch",
    )
    expected_boundary = {
        "incremental_cloud_cost_cny": "0.000000",
        "paid_resource_create_count": 0,
        "temporary_paid_compute_start_count": 0,
        "provider_payload_content_sent": False,
        "user_content_sent": False, "database_write_requested": False,
        "public_traffic_sent": False,
        "deleted_material": {
            "owned_temporary_file_count": 5, "owned_task_root_count": 1,
            "user_data_delete_count": 0,
            "recoverable_from_provider_history": True,
        },
    }
    _append(
        errors,
        _strict(value.get("cost_and_data_boundary"), expected_boundary),
        "cost/data boundary mismatch",
    )
    _append(
        errors,
        _strict(value.get("readiness"), expected_readiness or DEFAULT_READINESS),
        "readiness projection mismatch",
    )
    acceptance = value.get("terminal_acceptance_sha256")
    _append(
        errors,
        type(acceptance) is str and HEX64.fullmatch(acceptance) is not None
        and acceptance == terminal_acceptance_sha256(value),
        "terminal acceptance mismatch",
    )
    return errors


def validate_manifest_evidence(
    entries: Any, *, root: Path = ROOT,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    if type(entries) is not list:
        return ["Item28 manifest evidence must be a list"]
    if any(
        type(row) is not dict or set(row) != {"kind", "ref"}
        for row in entries
    ):
        return ["Item28 manifest evidence rows invalid"]
    path_refs = [row["ref"] for row in entries if row["kind"] == "path"]
    git_refs = [row["ref"] for row in entries if row["kind"] == "git"]
    if (
        len(path_refs) != len(REQUIRED_MANIFEST_PATH_REFS)
        or set(path_refs) != REQUIRED_MANIFEST_PATH_REFS
        or len(git_refs) != 1
        or set(git_refs) != REQUIRED_MANIFEST_GIT_REFS
        or len(entries) != len(REQUIRED_MANIFEST_PATH_REFS) + 1
    ):
        return ["Item28 exact direct evidence refs required"]
    try:
        value = load_evidence(root / EVIDENCE_REF)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return ["Item28 evidence unreadable: " + str(exc)]
    return validate_document(
        value, root=root, expected_readiness=expected_readiness,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    entries = [
        *(
            {"kind": "path", "ref": ref}
            for ref in sorted(REQUIRED_MANIFEST_PATH_REFS)
        ),
        {"kind": "git", "ref": EXECUTION_SOURCE_REVISION},
    ]
    errors = validate_manifest_evidence(
        entries, root=args.root, expected_readiness=DEFAULT_READINESS,
    )
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
