#!/usr/bin/env python3
"""Verify the single tracked Item 29 managed-capacity evidence document."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
EVIDENCE_SCHEMA = "noteai.item29.capacity-100-evidence.v1"
RESULT_SCHEMA = "noteai.item29.capacity-100-result.v1"
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-capacity-100-jobs-verified-20260824.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
EXECUTOR_REF = "deploy/production/capacity_100_jobs.py"
RENDERER_REF = "tools/render_item29_capacity_100_request_v1.py"
VERIFIER_REF = "tools/verify_capacity_100_jobs_evidence.py"
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
ITEM28_TERMINAL_ACCEPTANCE_SHA256 = (
    "55363294b82f21c6c0fd000e8dcf08f481775a2f63b2a9dd733056ffb4f85c9c"
)
ITEM28_DEPENDENCY = {
    "schema": "noteai.item29.item28-dependency.v1",
    "evidence_path": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
    "evidence_sha256": (
        "429b41e4e7be1549181bed195623718ce65d2d052257ea176da99e266fa598f8"
    ),
    "terminal_acceptance_sha256": ITEM28_TERMINAL_ACCEPTANCE_SHA256,
}
IMAGE = (
    "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@"
    "sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
)
IMAGE_CONFIG = "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
C17_REVISION = "cad5ce35664f617c6e19f90a6159285ddf975594"
DISPATCHER_UNIT_SHA256 = "8e2d9dc59b87585e5921f5c2b838db4c150efeebeb8e243e194bce586fc102fc"
WORKER_UNIT_SHA256 = "a3fa4407202620d5c3e0f6f1fd6de4babe564d3b0cea79c1cbded7a2e13fd200"
TARGET_SHA256 = {
    "API-C": hashlib.sha256(b"i-wz9j36od3nf2b1uw7bvg").hexdigest(),
    "Worker-C": hashlib.sha256(b"i-wz98zwcdtcmxzmmoso3w").hexdigest(),
    "Worker-F": hashlib.sha256(b"i-wz93qgvlu1bllpjcfwfj").hexdigest(),
}
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF, EXECUTOR_REF, RENDERER_REF, VERIFIER_REF,
}
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
EXPECTED_PROVIDER = {
    "fake_call_count": 100,
    "unique_fake_operation_count": 100,
    "duplicate_fake_call_count": 0,
    "real_provider_call_count": 0,
    "claude_label_count": 50,
    "kimi_label_count": 50,
    "ai_model_call_count": 0,
    "input_token_count": 0,
    "output_token_count": 0,
    "provider_cost_milli": 0,
}
EXPECTED_ROUTING = {
    "exact_operation_claim_count": 102,
    "takeover_count": 2,
    "global_recovery_call_count": 0,
    "global_claim_call_count": 0,
    "worker_c_index_start": 0,
    "worker_c_index_end": 49,
    "worker_f_index_start": 50,
    "worker_f_index_end": 99,
    "worker_c_takeover_index": 0,
    "worker_f_takeover_index": 50,
    "pre_provider_interrupt_count": 2,
    "stale_owner_provider_call_count": 0,
}
EXPECTED_RUNTIME = {
    "maximum_concurrent_admission_count": 100,
    "unique_operation_count": 100,
    "outbox_count": 100,
    "delivered_count": 100,
    "succeeded_count": 100,
    "lost_operation_count": 0,
    "claim_count": 102,
    "takeover_count": 2,
    "provider_attempt_count": 100,
    "provider_attempt_number_not_one_count": 0,
    "worker_c_completed_count": 50,
    "worker_f_completed_count": 50,
    "worker_c_takeover_index": 0,
    "worker_f_takeover_index": 50,
    "settlement_completed_count": 100,
    "settlement_refunded_count": 0,
    "settlement_needs_manual_count": 0,
    "charge_applied_count": 100,
    "complete_applied_count": 100,
    "usage_record_count": 100,
    "expected_credits_milli": 600_000,
    "actual_credits_milli": 600_000,
    "overcharge_credits_milli": 0,
    "payment_record_delta_count": 0,
    "cash_balance_delta_milli": 0,
    "ready_request_object_residue_count": 0,
    "ready_result_object_residue_count": 0,
    "primary_user_residue_count": 0,
    "admission_residue_count": 0,
    "idempotency_residue_count": 0,
    "pseudonymous_operation_audit_count": 100,
    "pseudonymous_provider_attempt_audit_count": 100,
    "pseudonymous_usage_audit_count": 100,
}
EXPECTED_EXECUTION_BOUNDARY = {
    "automatic_retry_count": 0,
    "real_provider_credentials_loaded": False,
    "cloud_control_plane_call_count": 0,
    "public_request_count": 0,
}
EXPECTED_STAGE_ACTIONS = (
    "preflight", "admit", "dispatch", "dispatch-readback",
    "preclaim-c", "preclaim-f", "process-c", "process-f",
    "source-cleanup-worker-c", "source-cleanup-worker-f",
    "observe", "cleanup", "source-cleanup-api-c",
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DECIMAL = re.compile(r"^(0|[1-9]\d*)\.\d{6}$")
MAX_EVIDENCE_BYTES = 256 * 1024


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
    ).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _gzip(raw: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output, mtime=0
    ) as handle:
        handle.write(raw)
    return output.getvalue()


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


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
        raise ValueError("evidence size/encoding invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if type(value) is not dict:
        raise ValueError("evidence root must be an object")
    return value


def terminal_acceptance_sha256(value: dict[str, Any]) -> str:
    return _sha(_canonical({
        key: item for key, item in value.items()
        if key != "terminal_acceptance_sha256"
    }))


def _git(*args: str, root: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True,
    )


def _git_file(revision: str, ref: str, *, root: Path) -> bytes | None:
    result = _git("show", f"{revision}:{ref}", root=root)
    return result.stdout if result.returncode == 0 else None


def _utc(value: Any) -> bool:
    if type(value) is not str or UTC.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return parsed <= datetime.now(timezone.utc)


def _validate_result(value: Any) -> list[str]:
    errors: list[str] = []
    top = {
        "schema", "task_id", "status", "item28_dependency", "headroom",
        "admission", "routing_and_recovery", "provider",
        "runtime_projection", "execution_boundary",
    }
    if type(value) is not dict or set(value) != top:
        return ["result fields mismatch"]
    _append(errors, value.get("schema") == RESULT_SCHEMA, "result schema mismatch")
    _append(errors, value.get("task_id") == TASK_ID, "result task mismatch")
    _append(errors, value.get("status") == "PASS", "result status mismatch")
    _append(
        errors, _strict(value.get("item28_dependency"), ITEM28_DEPENDENCY),
        "result Item28 dependency mismatch",
    )
    headroom = value.get("headroom")
    headroom_keys = {
        "database_idle_connection_headroom",
        "database_idle_connection_headroom_required",
        "api_c_memory_headroom_bytes",
        "api_c_memory_headroom_bytes_required",
        "api_c_pid_headroom", "api_c_pid_headroom_required",
        "headroom_gate_passed",
    }
    if type(headroom) is not dict or set(headroom) != headroom_keys:
        errors.append("headroom fields mismatch")
    else:
        minima = {
            "database_idle_connection_headroom": 120,
            "api_c_memory_headroom_bytes": 1_073_741_824,
            "api_c_pid_headroom": 160,
        }
        for key, minimum in minima.items():
            _append(
                errors,
                type(headroom.get(key)) is int and headroom[key] >= minimum,
                key + " insufficient",
            )
        _append(
            errors,
            _strict(
                {
                    "database_idle_connection_headroom_required": headroom.get(
                        "database_idle_connection_headroom_required"
                    ),
                    "api_c_memory_headroom_bytes_required": headroom.get(
                        "api_c_memory_headroom_bytes_required"
                    ),
                    "api_c_pid_headroom_required": headroom.get(
                        "api_c_pid_headroom_required"
                    ),
                    "headroom_gate_passed": headroom.get("headroom_gate_passed"),
                },
                {
                    "database_idle_connection_headroom_required": 120,
                    "api_c_memory_headroom_bytes_required": 1_073_741_824,
                    "api_c_pid_headroom_required": 160,
                    "headroom_gate_passed": True,
                },
            ),
            "headroom contract mismatch",
        )
    admission = value.get("admission")
    if type(admission) is not dict or set(admission) != {
        "barrier_participant_count", "concurrent_admission_count",
        "unique_operation_count", "operation_set_sha256",
    }:
        errors.append("admission fields mismatch")
    else:
        _append(
            errors,
            admission.get("barrier_participant_count") == 100
            and type(admission.get("barrier_participant_count")) is int
            and admission.get("concurrent_admission_count") == 100
            and type(admission.get("concurrent_admission_count")) is int
            and admission.get("unique_operation_count") == 100
            and type(admission.get("unique_operation_count")) is int
            and type(admission.get("operation_set_sha256")) is str
            and HEX64.fullmatch(admission["operation_set_sha256"]) is not None,
            "admission mismatch",
        )
    _append(
        errors, _strict(value.get("routing_and_recovery"), EXPECTED_ROUTING),
        "routing/recovery mismatch",
    )
    _append(errors, _strict(value.get("provider"), EXPECTED_PROVIDER), "provider mismatch")
    _append(
        errors, _strict(value.get("runtime_projection"), EXPECTED_RUNTIME),
        "runtime projection mismatch",
    )
    _append(
        errors,
        _strict(value.get("execution_boundary"), EXPECTED_EXECUTION_BOUNDARY),
        "execution boundary mismatch",
    )
    return errors


def _validate_source(value: Any, *, root: Path, verify_git: bool) -> list[str]:
    errors: list[str] = []
    expected_keys = {
        "branch", "execution_source_revision", "executor_ref", "renderer_ref",
        "verifier_ref", "executed_executor_bytes", "executed_executor_sha256",
        "executed_executor_gzip_sha256",
        "executed_renderer_sha256", "executed_verifier_sha256",
    }
    if type(value) is not dict or set(value) != expected_keys:
        return ["source binding fields mismatch"]
    _append(errors, value.get("branch") == SOURCE_BRANCH, "source branch mismatch")
    revision = value.get("execution_source_revision")
    _append(
        errors, type(revision) is str and HEX40.fullmatch(revision) is not None,
        "source revision mismatch",
    )
    _append(errors, value.get("executor_ref") == EXECUTOR_REF, "executor ref mismatch")
    _append(errors, value.get("renderer_ref") == RENDERER_REF, "renderer ref mismatch")
    _append(errors, value.get("verifier_ref") == VERIFIER_REF, "verifier ref mismatch")
    for key in (
        "executed_executor_sha256", "executed_renderer_sha256",
        "executed_verifier_sha256", "executed_executor_gzip_sha256",
    ):
        _append(
            errors,
            type(value.get(key)) is str and HEX64.fullmatch(value[key]) is not None,
            key + " mismatch",
        )
    _append(
        errors,
        type(value.get("executed_executor_bytes")) is int
        and value["executed_executor_bytes"] > 0,
        "executor bytes mismatch",
    )
    if verify_git and not errors:
        files = {
            EXECUTOR_REF: (
                value["executed_executor_sha256"],
                value["executed_executor_bytes"],
            ),
            RENDERER_REF: (value["executed_renderer_sha256"], None),
            VERIFIER_REF: (value["executed_verifier_sha256"], None),
        }
        for ref, (digest, size) in files.items():
            raw = _git_file(revision, ref, root=root)
            _append(errors, raw is not None, "source revision file missing: " + ref)
            if raw is not None:
                _append(errors, _sha(raw) == digest, "source digest mismatch: " + ref)
                if size is not None:
                    _append(errors, len(raw) == size, "source bytes mismatch: " + ref)
                if ref == EXECUTOR_REF:
                    _append(
                        errors,
                        _sha(_gzip(raw))
                        == value["executed_executor_gzip_sha256"],
                        "executor gzip digest mismatch",
                    )
    return errors


def _validate_stages(value: Any) -> list[str]:
    if type(value) is not list or tuple(
        row.get("action") if type(row) is dict else None for row in value
    ) != EXPECTED_STAGE_ACTIONS:
        return ["execution stage order mismatch"]
    errors: list[str] = []
    expected_keys = {
        "action", "target", "command_name", "terminal_status", "exit_code",
        "repeat_count", "dropped_count", "stdout_sha256",
        "started_at_utc", "finished_at_utc",
    }
    expected_targets = {
        "preflight": "API-C", "admit": "API-C", "dispatch": "API-C",
        "dispatch-readback": "API-C", "preclaim-c": "Worker-C",
        "preclaim-f": "Worker-F", "process-c": "Worker-C",
        "process-f": "Worker-F",
        "source-cleanup-worker-c": "Worker-C",
        "source-cleanup-worker-f": "Worker-F",
        "observe": "API-C", "cleanup": "API-C",
        "source-cleanup-api-c": "API-C",
    }
    parsed_times: dict[str, tuple[datetime, datetime]] = {}
    for row in value:
        action = row.get("action") if type(row) is dict else None
        _append(errors, type(row) is dict and set(row) == expected_keys, "stage fields mismatch")
        if type(row) is not dict:
            continue
        _append(errors, row.get("target") == expected_targets[action], "stage target mismatch")
        _append(
            errors,
            row.get("command_name") == f"noteai-item29-{action}-20260824-v1",
            "stage command name mismatch",
        )
        _append(errors, row.get("terminal_status") == "Success", "stage status mismatch")
        _append(errors, type(row.get("exit_code")) is int and row["exit_code"] == 0, "stage exit mismatch")
        _append(errors, type(row.get("repeat_count")) is int and row["repeat_count"] == 1, "stage repeat mismatch")
        _append(errors, type(row.get("dropped_count")) is int and row["dropped_count"] == 0, "stage dropped mismatch")
        _append(
            errors,
            type(row.get("stdout_sha256")) is str
            and HEX64.fullmatch(row["stdout_sha256"]) is not None,
            "stage stdout digest mismatch",
        )
        started = row.get("started_at_utc")
        finished = row.get("finished_at_utc")
        valid_times = _utc(started) and _utc(finished)
        _append(errors, valid_times, "stage clock mismatch")
        if valid_times:
            start_time = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            finish_time = datetime.strptime(
                finished, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            _append(errors, start_time <= finish_time, "stage interval mismatch")
            parsed_times[action] = (start_time, finish_time)
    if all(
        action in parsed_times
        for action in ("preclaim-c", "preclaim-f", "process-c", "process-f")
    ):
        lease_gate = max(
            parsed_times["preclaim-c"][1], parsed_times["preclaim-f"][1]
        ) + timedelta(seconds=15)
        _append(
            errors,
            min(
                parsed_times["process-c"][0], parsed_times["process-f"][0]
            ) >= lease_gate,
            "preclaim lease expiry interval mismatch",
        )
    return errors


def _validate_cost(value: Any) -> list[str]:
    expected_keys = {
        "incremental_cloud_cost_cny", "worker_c_billable_seconds",
        "worker_f_billable_seconds", "worker_c_hourly_quote_cny",
        "worker_f_hourly_quote_cny", "provider_cost_cny",
        "synthetic_user_create_count", "synthetic_user_delete_count",
        "real_user_data_read_count", "real_user_data_write_count",
        "public_request_count", "non_idempotent_replay_count",
        "provider_replay_count",
    }
    if type(value) is not dict or set(value) != expected_keys:
        return ["cost/data fields mismatch"]
    errors: list[str] = []
    for key in (
        "incremental_cloud_cost_cny", "worker_c_hourly_quote_cny",
        "worker_f_hourly_quote_cny", "provider_cost_cny",
    ):
        raw = value.get(key)
        valid = type(raw) is str and DECIMAL.fullmatch(raw) is not None
        try:
            valid = valid and Decimal(raw) >= 0
        except (InvalidOperation, TypeError):
            valid = False
        _append(errors, valid, key + " mismatch")
    _append(errors, value.get("provider_cost_cny") == "0.000000", "provider cost mismatch")
    for key in ("worker_c_billable_seconds", "worker_f_billable_seconds"):
        _append(
            errors, type(value.get(key)) is int and value[key] > 0,
            key + " mismatch",
        )
    exact = {
        "synthetic_user_create_count": 100,
        "synthetic_user_delete_count": 100,
        "real_user_data_read_count": 0,
        "real_user_data_write_count": 0,
        "public_request_count": 0,
        "non_idempotent_replay_count": 0,
        "provider_replay_count": 0,
    }
    for key, expected in exact.items():
        _append(
            errors, type(value.get(key)) is int and value[key] == expected,
            key + " mismatch",
        )
    return errors


def validate_document(
    value: Any, *, root: Path = ROOT,
    expected_readiness: dict[str, Any] | None = None,
    verify_git: bool = True,
) -> list[str]:
    errors: list[str] = []
    top = {
        "schema_version", "schema", "task_id", "status", "observed_at_utc",
        "source_binding", "predecessor", "managed_runtime",
        "source_transfers", "execution_stages", "result",
        "final_resource_state", "cost_and_data_boundary", "readiness",
        "terminal_acceptance_sha256",
    }
    if type(value) is not dict:
        return ["evidence root must be an object"]
    _append(errors, set(value) == top, "top-level fields mismatch")
    _append(errors, type(value.get("schema_version")) is int and value["schema_version"] == 1, "schema version mismatch")
    _append(errors, value.get("schema") == EVIDENCE_SCHEMA, "schema mismatch")
    _append(errors, value.get("task_id") == TASK_ID, "task id mismatch")
    _append(errors, value.get("status") == "PASS", "status mismatch")
    _append(errors, _utc(value.get("observed_at_utc")), "observed clock mismatch")
    source_binding = value.get("source_binding")
    errors.extend(_validate_source(source_binding, root=root, verify_git=verify_git))
    _append(
        errors,
        _strict(value.get("predecessor"), {
            "item28_terminal_acceptance_sha256": ITEM28_TERMINAL_ACCEPTANCE_SHA256,
        }),
        "predecessor mismatch",
    )
    _append(
        errors,
        _strict(value.get("managed_runtime"), {
            "target_instance_sha256": TARGET_SHA256,
            "c17_revision": C17_REVISION,
            "c17_image": IMAGE,
            "c17_image_config": IMAGE_CONFIG,
            "dispatcher_unit_sha256": DISPATCHER_UNIT_SHA256,
            "worker_unit_sha256": WORKER_UNIT_SHA256,
            "api_database_role": "noteai_app",
            "dispatcher_database_role": "noteai_ai_dispatcher",
            "worker_database_role": "noteai_ai_worker",
            "database_credential_transport": "private_docker_env_file",
        }),
        "managed runtime mismatch",
    )
    transfers = value.get("source_transfers")
    transfer_targets = ("API-C", "Worker-C", "Worker-F")
    if type(transfers) is not list or tuple(
        row.get("target") if type(row) is dict else None for row in transfers
    ) != transfer_targets:
        errors.append("source transfer order mismatch")
    else:
        for row in transfers:
            _append(
                errors,
                set(row) == {
                    "target", "terminal_status", "repeat_count",
                    "content_sha256", "overwrite", "source_residue_count",
                },
                "source transfer fields mismatch",
            )
            _append(errors, row.get("terminal_status") == "Success", "source transfer status mismatch")
            _append(errors, type(row.get("repeat_count")) is int and row["repeat_count"] == 1, "source transfer repeat mismatch")
            _append(
                errors,
                type(source_binding) is dict
                and row.get("content_sha256")
                == source_binding.get("executed_executor_gzip_sha256"),
                "source transfer digest mismatch",
            )
            _append(errors, row.get("overwrite") is False, "source transfer overwrite mismatch")
            _append(errors, type(row.get("source_residue_count")) is int and row["source_residue_count"] == 0, "source transfer residue mismatch")
    stages = value.get("execution_stages")
    errors.extend(_validate_stages(stages))
    if _utc(value.get("observed_at_utc")) and type(stages) is list:
        observed = datetime.strptime(
            value["observed_at_utc"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        for row in stages:
            if type(row) is dict and _utc(row.get("finished_at_utc")):
                finished = datetime.strptime(
                    row["finished_at_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                _append(errors, finished <= observed, "stage after observation")
    errors.extend(_validate_result(value.get("result")))
    _append(
        errors,
        _strict(value.get("final_resource_state"), {
            "api_c": {"status": "Running", "charge_type": "PrePaid"},
            "api_f": {"status": "Running", "charge_type": "PrePaid"},
            "builder": {"status": "Stopped", "charge_type": "PostPaid"},
            "worker_c": {"status": "Stopped", "charge_type": "PostPaid"},
            "worker_f": {"status": "Stopped", "charge_type": "PostPaid"},
            "temporary_compute_running_count": 0,
            "task_container_residue_count": 0,
            "task_file_residue_count": 0,
            "public_listener_count": 0,
            "temporary_security_rule_count": 0,
            "temporary_peering_count": 0,
            "temporary_route_count": 0,
        }),
        "final resource state mismatch",
    )
    errors.extend(_validate_cost(value.get("cost_and_data_boundary")))
    _append(
        errors,
        _strict(value.get("readiness"), expected_readiness or DEFAULT_READINESS),
        "readiness mismatch",
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
    if type(entries) is not list or any(type(row) is not dict for row in entries):
        return ["manifest evidence fields mismatch"]
    paths = {row.get("ref") for row in entries if row.get("kind") == "path"}
    git_refs = [row.get("ref") for row in entries if row.get("kind") == "git"]
    if paths != REQUIRED_MANIFEST_PATH_REFS or len(git_refs) != 1:
        return ["manifest evidence refs mismatch"]
    try:
        value = load_evidence(root / EVIDENCE_REF)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return ["evidence read failed: " + type(exc).__name__]
    source = value.get("source_binding") if type(value) is dict else None
    if type(source) is not dict or source.get("execution_source_revision") != git_refs[0]:
        return ["manifest source revision mismatch"]
    return validate_document(
        value, root=root, expected_readiness=expected_readiness, verify_git=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", nargs="?", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        value = load_evidence(args.evidence)
        errors = validate_document(value)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print("capacity_100_jobs=BLOCK " + type(exc).__name__)
        return 1
    if errors:
        print("capacity_100_jobs=BLOCK " + errors[0])
        return 1
    print("capacity_100_jobs=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
