#!/usr/bin/env python3
"""Build one Secret-free Item 28 receipt from retained raw provider bodies."""

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

from render_item28_internal_failure_rollback_request_v1 import (
    ACTION, COMMAND_NAME, REGION, canonical, parse_canonical,
    validate_run_command,
)
from validate_item28_internal_failure_rollback_result_v1 import (
    VALIDATOR_REF, validate_executor_result,
)


ROOT = Path(__file__).resolve().parents[1]
BUILDER_REF = "tools/build_item28_internal_failure_rollback_evidence_v1.py"
EXECUTOR_REF = "deploy/production/internal_failure_rollback.py"
RENDERER_REF = "tools/render_item28_internal_failure_rollback_request_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
RECEIPT_SCHEMA = "noteai.item28.provider-readback-receipt.v1"
CAPTURE_CONTRACT = "noteai.item28.root-only-provider-raw-closure.v1"
MAX_RAW_BYTES = 2 * 1024 * 1024
PAGE_SIZE = 50
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
RAW_RESPONSE_FILES = (
    "run-command-response.json", "pre-describe-commands.json",
    "pre-describe-invocations.json", "terminal-describe-commands.json",
    "terminal-describe-invocations.json", "terminal-describe-results.json",
)
PROVIDER_REQUEST_FILES = (
    "run-command-request.json", "pre-describe-commands-request.json",
    "pre-describe-invocations-request.json",
    "terminal-describe-commands-request.json",
    "terminal-describe-invocations-request.json",
    "terminal-describe-results-request.json",
)


class ClosureError(ValueError):
    def __init__(self, code):
        ValueError.__init__(self, code)
        self.code = code


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _commit(label, value):
    if type(value) is not str or not value:
        raise ClosureError(label)
    return _sha(
        b"noteai-item28-provider-commitment-v1\x00"
        + label.encode("ascii") + b"\x00" + value.encode("utf-8")
    )


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ClosureError("duplicate_json_key")
        value[key] = item
    return value


def _json(raw, label):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RAW_BYTES or b"\x00" in raw:
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


def _object(value, keys, label):
    if type(value) is not dict or not set(keys).issubset(value):
        raise ClosureError(label + "_schema")
    return value


def _string(value, label):
    if type(value) is not str or not value:
        raise ClosureError(label)
    return value


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise ClosureError(label)
    return value


def _utc(value, label):
    if type(value) is not str or UTC.fullmatch(value) is None:
        raise ClosureError(label)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ClosureError(label) from exc


def _strict(left, right):
    if type(left) is not type(right):
        return False
    if type(right) is dict:
        return set(left) == set(right) and all(_strict(left[key], item) for key, item in right.items())
    if type(right) is list:
        return len(left) == len(right) and all(_strict(a, b) for a, b in zip(left, right))
    return left == right


def _request(raw, expected, label):
    try:
        value = parse_canonical(raw)
    except Exception as exc:
        raise ClosureError(label + "_request") from exc
    if not _strict(value, expected):
        raise ClosureError(label + "_request_binding")
    return value


def _page(body, container, item, expected_total, label):
    _object(body, {"RequestId", "PageNumber", "PageSize", "TotalCount", container}, label)
    request_id = _string(body.get("RequestId"), label + "_request_id")
    wrapped = _object(body.get(container), {item}, label + "_wrapper")
    rows = wrapped.get(item)
    if (
        _integer(body.get("PageNumber"), label + "_page") != 1
        or _integer(body.get("PageSize"), label + "_size") != PAGE_SIZE
        or _integer(body.get("TotalCount"), label + "_total") != expected_total
        or type(rows) is not list or len(rows) != expected_total
        or any(type(row) is not dict for row in rows)
    ):
        raise ClosureError(label + "_incomplete_page")
    return request_id, rows


def _only(rows, predicate, label):
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise ClosureError(label)
    return matches[0]


def _binding(raw, prefix):
    return {prefix + "_raw_bytes": len(raw), prefix + "_raw_sha256": _sha(raw)}


def _canonical_binding(raw, prefix):
    return {prefix + "_bytes": len(raw), prefix + "_sha256": _sha(raw)}


def _source_binding(root, ref):
    path = root / ref
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o644
        ):
            raise ClosureError("source_identity")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ClosureError("source_identity")
            raw = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 2 * 1024 * 1024:
                    raise ClosureError("source_identity")
        finally:
            os.close(fd)
        after = path.lstat()
    except ClosureError:
        raise
    except OSError as exc:
        raise ClosureError("source_identity") from exc
    if (
        before.st_dev, before.st_ino, before.st_mode, before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev, after.st_ino, after.st_mode, after.st_size,
        after.st_mtime_ns,
    ):
        raise ClosureError("source_identity")
    return {"path": ref, "bytes": len(raw), "sha256": _sha(raw)}


def build_receipt(capture, *, source_revision, observed_at_utc, root=ROOT):
    if type(capture) is not dict or tuple(capture) != CAPTURE_FILES:
        raise ClosureError("capture_files")
    if any(type(raw) is not bytes for raw in capture.values()):
        raise ClosureError("capture_bytes")
    if type(source_revision) is not str or HEX40.fullmatch(source_revision) is None:
        raise ClosureError("source_revision")
    observed = _utc(observed_at_utc, "observed_at_utc")
    try:
        renderer_input = parse_canonical(capture["renderer-input.json"])
        run_request = parse_canonical(capture["run-command-request.json"])
        validation = validate_run_command(run_request, renderer_input, root=root)
    except Exception as exc:
        raise ClosureError("run_request_binding") from exc
    if validation.get("action") != ACTION or run_request.get("Name") != COMMAND_NAME:
        raise ClosureError("run_request_action")
    target = run_request["InstanceId"][0]
    run = _json(capture["run-command-response.json"], "run_response")
    _object(run, {"RequestId", "CommandId", "InvokeId"}, "run_response")
    run_request_id = _string(run.get("RequestId"), "run_request_id")
    command_id = _string(run.get("CommandId"), "command_id")
    invoke_id = _string(run.get("InvokeId"), "invoke_id")
    page = {"PageNumber": 1, "PageSize": PAGE_SIZE}
    expected_requests = {
        "pre-describe-commands-request.json": {"RegionId": REGION, "Name": COMMAND_NAME, **page},
        "pre-describe-invocations-request.json": {"RegionId": REGION, "CommandName": COMMAND_NAME, **page},
        "terminal-describe-commands-request.json": {"RegionId": REGION, "CommandId": command_id, "Name": COMMAND_NAME, **page},
        "terminal-describe-invocations-request.json": {"RegionId": REGION, "CommandId": command_id, "InvokeId": invoke_id, "InstanceId": target, **page},
        "terminal-describe-results-request.json": {"RegionId": REGION, "CommandId": command_id, "InvokeId": invoke_id, "InstanceId": target, **page},
    }
    for name, expected in expected_requests.items():
        _request(capture[name], expected, name)

    pre_command_request_id, pre_commands = _page(
        _json(capture["pre-describe-commands.json"], "pre_commands"),
        "Commands", "Command", 0, "pre_commands",
    )
    pre_invocation_request_id, pre_invocations = _page(
        _json(capture["pre-describe-invocations.json"], "pre_invocations"),
        "Invocations", "Invocation", 0, "pre_invocations",
    )
    if pre_commands or pre_invocations:
        raise ClosureError("pre_dispatch_history_nonzero")

    terminal_command_request_id, command_rows = _page(
        _json(capture["terminal-describe-commands.json"], "terminal_commands"),
        "Commands", "Command", 1, "terminal_commands",
    )
    readable = {
        "CommandId": command_id,
        **{key: run_request[key] for key in (
            "Name", "Type", "CommandContent", "Timeout", "WorkingDir",
            "EnableParameter",
        )},
    }
    command = _only(
        command_rows,
        lambda row: all(key in row and _strict(row[key], expected)
                        for key, expected in readable.items()),
        "terminal_command_match",
    )

    terminal_invocation_request_id, invocation_rows = _page(
        _json(capture["terminal-describe-invocations.json"], "terminal_invocations"),
        "Invocations", "Invocation", 1, "terminal_invocations",
    )
    invocation = _only(
        invocation_rows,
        lambda row: row.get("CommandId") == command_id and row.get("InvokeId") == invoke_id,
        "terminal_invocation_match",
    )
    _object(invocation, {
        "CommandId", "InvokeId", "CommandName", "InvocationStatus",
        "InvokeStatus", "RepeatMode", "Username", "TerminationMode",
        "InvokeInstances",
    }, "terminal_invocation")
    wrapper = _object(invocation.get("InvokeInstances"), {"InvokeInstance"}, "invoke_instances")
    instance_rows = wrapper.get("InvokeInstance")
    if type(instance_rows) is not list or len(instance_rows) != 1:
        raise ClosureError("invoke_instances")
    instance = _only(instance_rows, lambda row: row.get("InstanceId") == target, "terminal_instance")
    _object(instance, {
        "InstanceId", "InvocationStatus", "ExitCode", "Dropped", "Repeats",
        "InstanceInvokeStatus",
    }, "terminal_instance")
    dropped = _integer(instance.get("Dropped"), "invocation_dropped")
    repeats = _integer(instance.get("Repeats"), "invocation_repeats")
    if (
        invocation.get("CommandName") != COMMAND_NAME
        or invocation.get("InvocationStatus") != "Success"
        or invocation.get("InvokeStatus") != "Finished"
        or invocation.get("RepeatMode") != "Once"
        or invocation.get("Username") != "root"
        or invocation.get("TerminationMode") != "ProcessTree"
        or instance.get("InvocationStatus") != "Success"
        or instance.get("InstanceInvokeStatus") != "Finished"
        or _integer(instance.get("ExitCode"), "invocation_exit") != 0
        or dropped != 0 or repeats != 1
    ):
        raise ClosureError("terminal_invocation_result")

    results_body = _json(capture["terminal-describe-results.json"], "terminal_results")
    _object(results_body, {"RequestId", "Invocation"}, "terminal_results")
    results_request_id = _string(results_body.get("RequestId"), "results_request_id")
    result_invocation = _object(results_body.get("Invocation"), {
        "PageNumber", "PageSize", "TotalCount", "InvocationResults",
    }, "results_invocation")
    result_wrapper = _object(result_invocation.get("InvocationResults"), {"InvocationResult"}, "results_wrapper")
    result_rows = result_wrapper.get("InvocationResult")
    if (
        _integer(result_invocation.get("PageNumber"), "results_page") != 1
        or _integer(result_invocation.get("PageSize"), "results_size") != PAGE_SIZE
        or _integer(result_invocation.get("TotalCount"), "results_total") != 1
        or type(result_rows) is not list or len(result_rows) != 1
    ):
        raise ClosureError("results_rows")
    provider_result = _only(
        result_rows,
        lambda row: row.get("CommandId") == command_id
        and row.get("InvokeId") == invoke_id and row.get("InstanceId") == target,
        "provider_result_match",
    )
    _object(provider_result, {
        "CommandId", "InvokeId", "InstanceId", "InvocationStatus",
        "ExitCode", "Dropped", "Repeats", "Output", "StartTime",
        "FinishedTime",
    }, "provider_result")
    start = _utc(provider_result.get("StartTime"), "result_start")
    finished = _utc(provider_result.get("FinishedTime"), "result_finished")
    if (
        provider_result.get("InvocationStatus") != "Success"
        or _integer(provider_result.get("ExitCode"), "result_exit") != 0
        or _integer(provider_result.get("Dropped"), "result_dropped") != 0
        or _integer(provider_result.get("Repeats"), "result_repeats") != 1
        or provider_result.get("ErrorCode") not in {None, ""}
        or provider_result.get("ErrorInfo") not in {None, ""}
        or not start < finished <= observed
        or (finished - start).total_seconds() > 960
    ):
        raise ClosureError("provider_result")
    try:
        stdout = base64.b64decode(
            _string(provider_result.get("Output"), "result_output").encode("ascii"),
            validate=True,
        )
        result = parse_canonical(stdout)
    except Exception as exc:
        raise ClosureError("result_output") from exc
    result_errors, result_binding = validate_executor_result(result)
    if result_errors or result_binding is None:
        raise ClosureError("result_semantics")
    request_ids = (
        run_request_id, pre_command_request_id, pre_invocation_request_id,
        terminal_command_request_id, terminal_invocation_request_id,
        results_request_id,
    )
    if len(set(request_ids)) != len(request_ids):
        raise ClosureError("request_ids_unique")
    manifest = canonical({
        "capture_contract": CAPTURE_CONTRACT,
        "files": [{"name": name, "bytes": len(capture[name]), "sha256": _sha(capture[name])}
                  for name in CAPTURE_FILES],
    })
    return {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "action": ACTION,
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "observed_at_utc": observed_at_utc,
        "source_revision": source_revision,
        "source_binding": {
            "executor": _source_binding(root, EXECUTOR_REF),
            "renderer": _source_binding(root, RENDERER_REF),
            "builder": _source_binding(root, BUILDER_REF),
            "validator": _source_binding(root, VALIDATOR_REF),
        },
        "predecessors": validation["predecessor_acceptance_sha256"],
        "raw_closure": {
            "capture_contract": CAPTURE_CONTRACT,
            "capture_file_count": len(CAPTURE_FILES),
            "capture_manifest_canonical_bytes": len(manifest),
            "capture_manifest_canonical_sha256": _sha(manifest),
            "raw_provider_bodies_retained_root_only": True,
            "raw_provider_value_emitted_count": 0,
            "raw_response_commitment_count": len(RAW_RESPONSE_FILES),
            "provider_request_commitment_count": len(PROVIDER_REQUEST_FILES),
        },
        "request": {
            "canonical_bytes": len(capture["run-command-request.json"]),
            "canonical_sha256": _sha(capture["run-command-request.json"]),
            "command_name": COMMAND_NAME,
            "command_content_sha256": validation["command_content_sha256"],
            "executor_sha256": validation["executor_sha256"],
            "client_token_sha256": _commit("client-token", run_request["ClientToken"]),
            "target_identity_sha256": _commit("target", target),
            "provider_request_id_sha256": _commit("run-request", run_request_id),
            "provider_command_id_sha256": _commit("command-id", command_id),
            "provider_invoke_id_sha256": _commit("invoke-id", invoke_id),
            **_binding(capture["run-command-response.json"], "run_command_response"),
        },
        "pre_dispatch": {
            "all_pages": True,
            "page_number": 1,
            "page_size": PAGE_SIZE,
            "exact_command_name_history_count": 0,
            "exact_invocation_name_history_count": 0,
            "provider_client_token_readback_supported": False,
            **_canonical_binding(capture["pre-describe-commands-request.json"], "commands_request"),
            **_binding(capture["pre-describe-commands.json"], "commands_response"),
            **_canonical_binding(capture["pre-describe-invocations-request.json"], "invocations_request"),
            **_binding(capture["pre-describe-invocations.json"], "invocations_response"),
        },
        "terminal_readback": {
            "all_pages": True,
            "command_match_count": 1,
            "invocation_match_count": 1,
            "result_match_count": 1,
            "provider_status": "Finished",
            "provider_result_status": "Success",
            "exit_code": 0,
            "dropped_count": 0,
            "repeat_count": 1,
            "request_canonical_sha256": _sha(capture["run-command-request.json"]),
            "provider_readable_run_command_field_count": len(readable),
            "provider_readable_run_command_sha256": _sha(canonical(readable)),
            **_binding(capture["terminal-describe-commands.json"], "commands_response"),
            **_binding(capture["terminal-describe-invocations.json"], "invocations_response"),
            **_binding(capture["terminal-describe-results.json"], "results_response"),
        },
        "result": result,
        "result_binding": result_binding,
        "execution_boundary": {
            "dispatch_count": 1,
            "automatic_retry_count": 0,
            "same_request_resubmit_allowed": False,
            "same_invocation_replay_allowed": False,
            "provider_unknown": False,
            "local_o_excl_plan_nonce_required": True,
            "provider_client_token_readback_supported": False,
            "provider_call_count": 0,
            "oss_mutation_count": 0,
            "iam_mutation_count": 0,
            "production_database_mutation_count": 0,
            "cloud_resource_create_count": 0,
        },
    }


def terminal_acceptance_sha256(receipt):
    return _sha(canonical({
        "schema": receipt.get("schema"),
        "task_id": receipt.get("task_id"),
        "status": receipt.get("status"),
        "source_revision": receipt.get("source_revision"),
        "source_binding": receipt.get("source_binding"),
        "predecessors": receipt.get("predecessors"),
        "request_sha256": (receipt.get("request") or {}).get("canonical_sha256"),
        "result_sha256": (receipt.get("result_binding") or {}).get("terminal_acceptance_sha256"),
        "raw_manifest_sha256": (receipt.get("raw_closure") or {}).get("capture_manifest_canonical_sha256"),
        "execution_boundary": receipt.get("execution_boundary"),
    })[:-1])


def _stable(row):
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def load_root_only_capture(directory):
    try:
        parent = directory.lstat()
        names = {item.name for item in directory.iterdir()}
    except OSError as exc:
        raise ClosureError("capture_root_identity") from exc
    if (
        not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or names != set(CAPTURE_FILES)
    ):
        raise ClosureError("capture_root_identity")
    capture = {}
    for name in CAPTURE_FILES:
        path = directory / name
        try:
            before = path.lstat()
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                raw = b""
                while True:
                    chunk = os.read(fd, min(65536, MAX_RAW_BYTES + 1 - len(raw)))
                    if not chunk:
                        break
                    raw += chunk
                    if len(raw) > MAX_RAW_BYTES:
                        break
                closed = os.fstat(fd)
            finally:
                os.close(fd)
            after = path.lstat()
        except OSError as exc:
            raise ClosureError("capture_file_identity") from exc
        if (
            not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.getuid() or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= len(raw) <= MAX_RAW_BYTES
            or _stable(before) != _stable(opened)
            or _stable(opened) != _stable(closed)
            or _stable(closed) != _stable(after)
        ):
            raise ClosureError("capture_file_identity")
        capture[name] = raw
    return capture


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    args = parser.parse_args(argv)
    try:
        capture = load_root_only_capture(args.capture_dir)
        receipt = build_receipt(
            capture, source_revision=args.source_revision,
            observed_at_utc=args.observed_at_utc,
        )
        sys.stdout.buffer.write(canonical(receipt))
        return 0
    except (ClosureError, OSError) as exc:
        code = exc.code if isinstance(exc, ClosureError) else "capture_io"
        sys.stderr.write(code + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
