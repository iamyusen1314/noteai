#!/usr/bin/env python3
"""Build one Secret-free Item 27 receipt from retained provider raw bodies.

This tool is the only supported bridge from the root-only execution closure to
the committed receipt.  It performs no provider call.  The eight fixed input
files retain the exact request/response bytes and provider identifiers; stdout
contains only irreversible commitments plus the executor's Secret-free result.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from render_item27_internal_smoke_requests_v1 import (
    ACTIONS,
    REGION,
    canonical,
    derive_client_tokens,
    parse_canonical,
    validate_run_command,
)
from validate_item27_internal_smoke_result_v1 import (
    VALIDATOR_REF,
    validate_executor_result,
)


ROOT = Path(__file__).resolve().parents[1]
BUILDER_REF = "tools/build_item27_internal_smoke_evidence_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
RESULT_SCHEMA = "noteai.item27.internal-zero-provider-smoke.v1"
RECEIPT_SCHEMA = "noteai.item27.provider-readback-receipt.v1"
CAPTURE_CONTRACT = "noteai.item27.root-only-provider-raw-closure.v1"
MAX_RAW_BYTES = 2 * 1024 * 1024
DESCRIBE_PAGE_SIZE = 50
HEX40 = re.compile(r"^[0-9a-f]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CAPTURE_FILES = (
    "renderer-input.json",
    "run-command-request.json",
    "run-command-response.json",
    "pre-describe-commands-request.json",
    "pre-describe-commands.json",
    "pre-describe-invocations-request.json",
    "pre-describe-invocations.json",
    "terminal-describe-commands-request.json",
    "terminal-describe-commands.json",
    "terminal-describe-invocations-request.json",
    "terminal-describe-invocations.json",
    "terminal-describe-results-request.json",
    "terminal-describe-results.json",
)
PROVIDER_REQUEST_FILES = (
    "run-command-request.json",
    "pre-describe-commands-request.json",
    "pre-describe-invocations-request.json",
    "terminal-describe-commands-request.json",
    "terminal-describe-invocations-request.json",
    "terminal-describe-results-request.json",
)
PROVIDER_RAW_RESPONSE_FILES = (
    "run-command-response.json",
    "pre-describe-commands.json",
    "pre-describe-invocations.json",
    "terminal-describe-commands.json",
    "terminal-describe-invocations.json",
    "terminal-describe-results.json",
)


class ClosureError(ValueError):
    """A fixed, non-sensitive raw-closure validation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _commit(label: str, value: str) -> str:
    if type(value) is not str or not value:
        raise ClosureError(label)
    return _sha256(
        b"noteai-item27-provider-commitment-v1\x00"
        + label.encode("ascii")
        + b"\x00"
        + value.encode("utf-8")
    )


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClosureError("duplicate_json_key")
        result[key] = value
    return result


def _json_body(raw: bytes, label: str) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_RAW_BYTES
        or b"\x00" in raw
    ):
        raise ClosureError(label + "_shape")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except ClosureError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClosureError(label + "_json") from exc
    if type(value) is not dict:
        raise ClosureError(label + "_object")
    return value


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise ClosureError(label)
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ClosureError(label)
    return value


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or UTC.fullmatch(value) is None:
        raise ClosureError(label)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ClosureError(label) from exc


def _strict_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict_equal(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict_equal(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ClosureError(label + "_schema")
    return value


def _provider_object(
    value: Any, required_keys: set[str], label: str
) -> dict[str, Any]:
    """Project required provider fields while retaining the complete raw body."""

    if type(value) is not dict or not required_keys.issubset(value):
        raise ClosureError(label + "_schema")
    return value


def _describe_request(
    raw: bytes, expected: dict[str, Any], label: str
) -> dict[str, Any]:
    try:
        value = parse_canonical(raw)
    except Exception as exc:
        raise ClosureError(label + "_request") from exc
    if not _strict_equal(value, expected) or type(value.get("PageNumber")) is not int \
            or type(value.get("PageSize")) is not int:
        raise ClosureError(label + "_request_binding")
    return value


def _page(
    body: dict[str, Any], container: str, item: str, label: str,
    *, expected_total: int,
) -> tuple[str, list[dict[str, Any]]]:
    _provider_object(
        body,
        {"RequestId", "PageNumber", "PageSize", "TotalCount", container},
        label,
    )
    request_id = _string(body.get("RequestId"), label + "_request_id")
    page_number = _integer(body.get("PageNumber"), label + "_page_number")
    page_size = _integer(body.get("PageSize"), label + "_page_size")
    total = _integer(body.get("TotalCount"), label + "_total_count")
    wrapped = body.get(container)
    _provider_object(wrapped, {item}, label + "_wrapper")
    rows = wrapped.get(item) if type(wrapped) is dict else None
    if (
        page_number != 1
        or page_size != DESCRIBE_PAGE_SIZE
        or total != expected_total
        or type(rows) is not list
        or len(rows) != total
        or any(type(row) is not dict for row in rows)
    ):
        raise ClosureError(label + "_incomplete_page")
    return request_id, rows


def _only(rows: list[dict[str, Any]], predicate, label: str) -> dict[str, Any]:
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise ClosureError(label)
    return matches[0]


def _raw_binding(raw: bytes, prefix: str) -> dict[str, Any]:
    return {
        prefix + "_raw_bytes": len(raw),
        prefix + "_raw_sha256": _sha256(raw),
    }


def _canonical_binding(raw: bytes, prefix: str) -> dict[str, Any]:
    return {
        prefix + "_bytes": len(raw),
        prefix + "_sha256": _sha256(raw),
    }


def _capture_manifest(capture: dict[str, bytes]) -> tuple[dict[str, Any], bytes]:
    value = {
        "capture_contract": CAPTURE_CONTRACT,
        "files": [
            {
                "name": name,
                "bytes": len(capture[name]),
                "sha256": _sha256(capture[name]),
            }
            for name in CAPTURE_FILES
        ],
    }
    return value, canonical(value)


def terminal_acceptance_sha256(receipt: dict[str, Any]) -> str:
    """Commit one complete terminal receipt without a self-referential field."""

    if type(receipt) is not dict:
        raise ClosureError("terminal_acceptance")
    value = dict(receipt)
    value.pop("terminal_acceptance_sha256", None)
    return _sha256(
        b"noteai-item27-terminal-acceptance-v1\x00" + canonical(value)
    )


def build_receipt(
    *,
    action: str,
    source_revision: str,
    observed_at_utc: str,
    capture: dict[str, bytes],
    root: Path = ROOT,
) -> dict[str, Any]:
    """Parse all raw bodies and return one canonicalizable Secret-free receipt."""

    if action not in ACTIONS:
        raise ClosureError("action")
    if type(source_revision) is not str or HEX40.fullmatch(source_revision) is None:
        raise ClosureError("source_revision")
    if type(observed_at_utc) is not str or UTC.fullmatch(observed_at_utc) is None:
        raise ClosureError("observed_at_utc")
    if type(capture) is not dict or tuple(capture) != CAPTURE_FILES:
        raise ClosureError("capture_files")
    if any(type(raw) is not bytes for raw in capture.values()):
        raise ClosureError("capture_bytes")

    try:
        renderer_input = parse_canonical(capture["renderer-input.json"])
        request = parse_canonical(capture["run-command-request.json"])
        validation = validate_run_command(request, renderer_input)
    except Exception as exc:
        raise ClosureError("request_binding") from exc
    if validation.get("action") != action:
        raise ClosureError("request_action")
    spec = ACTIONS[action]
    target = request["InstanceId"][0]
    request_raw = capture["run-command-request.json"]
    request_sha = _sha256(request_raw)
    predecessor_acceptance = validation["predecessor_acceptance_sha256"]
    token_plan = derive_client_tokens(
        renderer_input["plan_nonce"], predecessor_acceptance
    )
    token_plan_sha = _sha256(canonical(token_plan))

    run = _json_body(capture["run-command-response.json"], "run_command")
    _provider_object(
        run, {"RequestId", "CommandId", "InvokeId"}, "run_command"
    )
    run_request_id = _string(run.get("RequestId"), "run_request_id")
    command_id = _string(run.get("CommandId"), "run_command_id")
    invoke_id = _string(run.get("InvokeId"), "run_invoke_id")

    page = {"PageNumber": 1, "PageSize": DESCRIBE_PAGE_SIZE}
    describe_requests = {
        "pre_commands": _describe_request(
            capture["pre-describe-commands-request.json"],
            {"RegionId": REGION, "Name": request["Name"], **page},
            "pre_commands",
        ),
        "pre_invocations": _describe_request(
            capture["pre-describe-invocations-request.json"],
            {
                "RegionId": REGION, "CommandName": request["Name"],
                **page,
            },
            "pre_invocations",
        ),
        "terminal_commands": _describe_request(
            capture["terminal-describe-commands-request.json"],
            {
                "RegionId": REGION, "CommandId": command_id,
                "Name": request["Name"], **page,
            },
            "terminal_commands",
        ),
        "terminal_invocations": _describe_request(
            capture["terminal-describe-invocations-request.json"],
            {
                "RegionId": REGION, "CommandId": command_id,
                "InvokeId": invoke_id, "InstanceId": target, **page,
            },
            "terminal_invocations",
        ),
        "terminal_results": _describe_request(
            capture["terminal-describe-results-request.json"],
            {
                "RegionId": REGION, "CommandId": command_id,
                "InvokeId": invoke_id, "InstanceId": target, **page,
            },
            "terminal_results",
        ),
    }

    pre_commands_body = _json_body(
        capture["pre-describe-commands.json"], "pre_commands"
    )
    pre_commands_request_id, pre_commands = _page(
        pre_commands_body, "Commands", "Command", "pre_commands",
        expected_total=0,
    )
    pre_invocations_body = _json_body(
        capture["pre-describe-invocations.json"], "pre_invocations"
    )
    pre_invocations_request_id, pre_invocations = _page(
        pre_invocations_body, "Invocations", "Invocation", "pre_invocations",
        expected_total=0,
    )
    if pre_commands or pre_invocations:
        raise ClosureError("pre_dispatch_history_nonzero")

    terminal_commands_body = _json_body(
        capture["terminal-describe-commands.json"], "terminal_commands"
    )
    terminal_commands_request_id, terminal_commands = _page(
        terminal_commands_body, "Commands", "Command", "terminal_commands",
        expected_total=1,
    )
    command_expected = {
        "CommandId": command_id,
        **{
            key: request[key]
            for key in (
                "Name", "Type", "CommandContent", "Timeout",
                "WorkingDir", "EnableParameter",
            )
        },
    }
    _exact(command_expected, set(command_expected), "command_expected")
    _provider_object(
        terminal_commands[0], set(command_expected), "terminal_command_row"
    )
    command = _only(
        terminal_commands,
        lambda row: all(
            key in row and _strict_equal(row[key], expected)
            for key, expected in command_expected.items()
        ),
        "terminal_command_match",
    )

    terminal_invocations_body = _json_body(
        capture["terminal-describe-invocations.json"], "terminal_invocations"
    )
    terminal_invocations_request_id, terminal_invocations = _page(
        terminal_invocations_body,
        "Invocations",
        "Invocation",
        "terminal_invocations",
        expected_total=1,
    )
    _provider_object(
        terminal_invocations[0],
        {
            "CommandId", "InvokeId", "CommandName", "InvocationStatus",
            "InvokeStatus", "RepeatMode", "Username", "TerminationMode",
            "InvokeInstances",
        },
        "terminal_invocation_row",
    )
    invocation = _only(
        terminal_invocations,
        lambda row: row.get("CommandId") == command_id
        and row.get("InvokeId") == invoke_id,
        "terminal_invocation_match",
    )
    invoke_instances = invocation.get("InvokeInstances")
    _provider_object(
        invoke_instances, {"InvokeInstance"},
        "terminal_invoke_instances_wrapper",
    )
    instance_rows = (
        invoke_instances.get("InvokeInstance")
        if type(invoke_instances) is dict
        else None
    )
    if (
        type(instance_rows) is not list
        or len(instance_rows) != 1
    ):
        raise ClosureError("terminal_invoke_instances")
    _provider_object(
        instance_rows[0],
        {
            "InstanceId", "InvocationStatus", "ExitCode", "Dropped",
            "Repeats", "InstanceInvokeStatus",
        },
        "terminal_invoke_instance_row",
    )
    instance = _only(
        instance_rows,
        lambda row: type(row) is dict and row.get("InstanceId") == target,
        "terminal_instance_match",
    )
    invocation_dropped = _integer(instance.get("Dropped"), "terminal_dropped")
    invocation_repeats = _integer(instance.get("Repeats"), "terminal_repeats")
    if (
        invocation.get("InvocationStatus") != "Success"
        or invocation.get("InvokeStatus") != "Finished"
        or invocation.get("CommandName") != request["Name"]
        or invocation.get("Username") != request["Username"]
        or invocation.get("RepeatMode") != request["RepeatMode"]
        or invocation.get("TerminationMode") != request["TerminationMode"]
        or instance.get("InvocationStatus") != "Success"
        or instance.get("InstanceInvokeStatus") != "Finished"
        or _integer(instance.get("ExitCode"), "terminal_exit_code") != 0
        or invocation_dropped != 0
        or invocation_repeats != 1
    ):
        raise ClosureError("terminal_invocation_result")

    terminal_results_body = _json_body(
        capture["terminal-describe-results.json"], "terminal_results"
    )
    _provider_object(
        terminal_results_body,
        {"RequestId", "Invocation"},
        "terminal_results",
    )
    results_request_id = _string(
        terminal_results_body.get("RequestId"), "terminal_results_request_id"
    )
    invocation_wrapper = terminal_results_body.get("Invocation")
    _provider_object(
        invocation_wrapper,
        {"PageNumber", "PageSize", "TotalCount", "InvocationResults"},
        "terminal_results_invocation_wrapper",
    )
    results_wrapper = (
        invocation_wrapper.get("InvocationResults")
        if type(invocation_wrapper) is dict
        else None
    )
    _provider_object(
        results_wrapper, {"InvocationResult"},
        "terminal_results_wrapper",
    )
    result_rows = (
        results_wrapper.get("InvocationResult")
        if type(results_wrapper) is dict
        else None
    )
    if (
        _integer(
            invocation_wrapper.get("PageNumber"),
            "terminal_results_page_number",
        ) != 1
        or _integer(
            invocation_wrapper.get("PageSize"),
            "terminal_results_page_size",
        ) != DESCRIBE_PAGE_SIZE
        or _integer(
            invocation_wrapper.get("TotalCount"),
            "terminal_results_top_total",
        ) != 1
        or type(result_rows) is not list
        or len(result_rows) != 1
    ):
        raise ClosureError("terminal_results_rows")
    _provider_object(
        result_rows[0],
        {
            "CommandId", "InvokeId", "InstanceId", "InvocationStatus",
            "ExitCode", "Dropped", "Repeats", "Output", "StartTime",
            "FinishedTime",
        },
        "terminal_result_row",
    )
    provider_result = _only(
        result_rows,
        lambda row: type(row) is dict
        and row.get("CommandId") == command_id
        and row.get("InvokeId") == invoke_id
        and row.get("InstanceId") == target,
        "terminal_result_match",
    )
    result_dropped = _integer(provider_result.get("Dropped"), "result_dropped")
    result_repeats = _integer(provider_result.get("Repeats"), "result_repeats")
    provider_start_time = _utc(
        provider_result.get("StartTime"), "result_start_time"
    )
    provider_finished_time = _utc(
        provider_result.get("FinishedTime"), "result_finished_time"
    )
    observed_time = _utc(observed_at_utc, "observed_at_utc")
    if (
        provider_result.get("InvocationStatus") != "Success"
        or _integer(provider_result.get("ExitCode"), "result_exit_code") != 0
        or result_dropped != 0
        or result_repeats != 1
        or result_dropped != invocation_dropped
        or result_repeats != invocation_repeats
        or provider_result.get("ErrorCode") not in {None, ""}
        or provider_result.get("ErrorInfo") not in {None, ""}
        or not provider_start_time < provider_finished_time <= observed_time
    ):
        raise ClosureError("terminal_provider_result")
    output = _string(provider_result.get("Output"), "result_output")
    try:
        stdout = base64.b64decode(output.encode("ascii"), validate=True)
        result = parse_canonical(stdout)
    except Exception as exc:
        raise ClosureError("result_stdout") from exc
    if (
        result.get("schema") != RESULT_SCHEMA
        or result.get("task_id") != TASK_ID
        or result.get("status") != "PASS"
        or result.get("mode") != spec.host_mode
    ):
        raise ClosureError("result_identity")

    request_ids = (
        run_request_id,
        pre_commands_request_id,
        pre_invocations_request_id,
        terminal_commands_request_id,
        terminal_invocations_request_id,
        results_request_id,
    )
    if len(set(request_ids)) != len(request_ids):
        raise ClosureError("provider_request_ids_unique")
    manifest, manifest_raw = _capture_manifest(capture)
    result_errors, _derived = validate_executor_result(result, action)
    if result_errors:
        raise ClosureError("executor_result_semantics")

    builder_path = root / BUILDER_REF
    builder_sha = _sha256(builder_path.read_bytes())
    validator_path = root / VALIDATOR_REF
    validator_sha = _sha256(validator_path.read_bytes())

    command_binding = {
        "command_name": request["Name"],
        "command_content_sha256": validation["command_content_sha256"],
        "wrapper_sha256": validation["wrapper_sha256"],
        "executor_sha256": validation["executor_sha256"],
    }
    receipt = {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "action": action,
        "mode": spec.host_mode,
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "observed_at_utc": observed_at_utc,
        "source_revision": source_revision,
        "raw_closure": {
            "capture_contract": CAPTURE_CONTRACT,
            "capture_file_count": len(CAPTURE_FILES),
            "capture_manifest_canonical_bytes": len(manifest_raw),
            "capture_manifest_canonical_sha256": _sha256(manifest_raw),
            "raw_body_total_bytes": sum(len(raw) for raw in capture.values()),
            "raw_body_aggregate_sha256": _sha256(
                b"".join(
                    name.encode("ascii") + b"\x00" + bytes.fromhex(row["sha256"])
                    for name, row in zip(CAPTURE_FILES, manifest["files"])
                )
            ),
            "builder": {"path": BUILDER_REF, "sha256": builder_sha},
            "executor_result_validator": {
                "path": VALIDATOR_REF,
                "sha256": validator_sha,
            },
            "provider_fields_parsed_from_raw": True,
            "provider_raw_bodies_retained_complete": True,
            "provider_response_projection_only": True,
            "receipt_emitted_by_builder": True,
            "executor_result_semantics_verified": True,
        },
        "request": {
            "canonical_bytes": len(request_raw),
            "canonical_sha256": request_sha,
            **command_binding,
            "client_token_sha256": _commit("client-token", request["ClientToken"]),
            "client_token_plan_sha256": token_plan_sha,
            "predecessor_acceptance_sha256": predecessor_acceptance,
            "target_identity_sha256": _commit("target-identity", target),
            "target_plan_slot": spec.target,
            "target_count": 1,
            **_raw_binding(capture["run-command-response.json"], "run_command_response"),
            "provider_request_id_sha256": _commit("run-request-id", run_request_id),
            "provider_command_id_sha256": _commit("command-id", command_id),
        },
        "pre_dispatch": {
            "all_pages": True,
            "page_number": 1,
            "page_size": DESCRIBE_PAGE_SIZE,
            **_canonical_binding(
                capture["pre-describe-commands-request.json"],
                "describe_commands_request_canonical",
            ),
            "describe_commands_request_id_sha256": _commit(
                "pre-commands-request-id", pre_commands_request_id
            ),
            **_raw_binding(capture["pre-describe-commands.json"], "describe_commands"),
            **_canonical_binding(
                capture["pre-describe-invocations-request.json"],
                "describe_invocations_request_canonical",
            ),
            "describe_invocations_request_id_sha256": _commit(
                "pre-invocations-request-id", pre_invocations_request_id
            ),
            **_raw_binding(
                capture["pre-describe-invocations.json"], "describe_invocations"
            ),
            "exact_command_history_count": 0,
            "exact_invocation_history_count": 0,
            "exact_name_history_count": 0,
            "provider_client_token_readback_supported": False,
        },
        "terminal_readback": {
            "all_pages": True,
            "page_number": 1,
            "page_size": DESCRIBE_PAGE_SIZE,
            **_canonical_binding(
                capture["terminal-describe-commands-request.json"],
                "describe_commands_request_canonical",
            ),
            "describe_commands_request_id_sha256": _commit(
                "terminal-commands-request-id", terminal_commands_request_id
            ),
            **_raw_binding(
                capture["terminal-describe-commands.json"], "describe_commands"
            ),
            **_canonical_binding(
                capture["terminal-describe-invocations-request.json"],
                "describe_invocations_request_canonical",
            ),
            "describe_invocations_request_id_sha256": _commit(
                "terminal-invocations-request-id", terminal_invocations_request_id
            ),
            **_raw_binding(
                capture["terminal-describe-invocations.json"], "describe_invocations"
            ),
            **_canonical_binding(
                capture["terminal-describe-results-request.json"],
                "describe_results_request_canonical",
            ),
            "describe_results_request_id_sha256": _commit(
                "terminal-results-request-id", results_request_id
            ),
            **_raw_binding(capture["terminal-describe-results.json"], "describe_results"),
            "provider_command_id_sha256": _commit("command-id", command_id),
            "provider_invoke_id_sha256": _commit("invoke-id", invoke_id),
            "command_match_count": 1,
            "invocation_match_count": 1,
            "result_match_count": 1,
            "status": invocation["InvokeStatus"],
            "provider_result_status": "Success",
            "provider_start_time_utc": provider_result["StartTime"],
            "provider_finished_time_utc": provider_result["FinishedTime"],
            "exit_code": 0,
            "dropped_count": result_dropped,
            "repeat_count": result_repeats,
            "provider_readable_run_command_field_count": len(command_expected),
            "provider_readable_run_command_sha256": _sha256(
                canonical(command_expected)
            ),
            "request_canonical_sha256": request_sha,
            "command_content_sha256": validation["command_content_sha256"],
            "target_identity_sha256": _commit("target-identity", target),
        },
        "result_binding": {
            "stdout_canonical_bytes": len(stdout),
            "stdout_canonical_sha256": _sha256(stdout),
            "result_semantic_sha256": _sha256(stdout[:-1]),
            "stderr_bytes": 0,
            "stderr_sha256": _sha256(b""),
            "schema": RESULT_SCHEMA,
            "task_id": TASK_ID,
            "status": "PASS",
            "mode": spec.host_mode,
        },
        "execution_boundary": {
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
            "provider_identifier_commitment_count": len(request_ids) + 2,
            "secret_value_count": 0,
        },
        "result": result,
    }
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(receipt)
    return receipt


def _stable(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def load_root_only_capture(directory: Path) -> dict[str, bytes]:
    try:
        parent = directory.lstat()
    except OSError as exc:
        raise ClosureError("capture_directory") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or set(item.name for item in directory.iterdir()) != set(CAPTURE_FILES)
    ):
        raise ClosureError("capture_directory")
    capture: dict[str, bytes] = {}
    for name in CAPTURE_FILES:
        path = directory / name
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            before = path.lstat()
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                raw = os.read(descriptor, MAX_RAW_BYTES + 1)
                closed = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            after = path.lstat()
        except OSError as exc:
            raise ClosureError("capture_file") from exc
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= len(raw) <= MAX_RAW_BYTES
            or _stable(before) != _stable(opened)
            or _stable(opened) != _stable(closed)
            or _stable(closed) != _stable(after)
        ):
            raise ClosureError("capture_file")
        capture[name] = raw
    return capture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=tuple(ACTIONS))
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--capture-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = build_receipt(
            action=args.action,
            source_revision=args.source_revision,
            observed_at_utc=args.observed_at_utc,
            capture=load_root_only_capture(args.capture_dir),
        )
        output = canonical(receipt)
    except ClosureError as exc:
        sys.stderr.write("ITEM27_RAW_CLOSURE_FAILED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM27_RAW_CLOSURE_FAILED:internal\n")
        return 2
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
