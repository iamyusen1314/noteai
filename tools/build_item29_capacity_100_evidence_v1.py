#!/usr/bin/env python3
"""Build one Secret-free Item 29 receipt from retained raw provider bodies."""

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


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_item29_capacity_100_request_v1 as renderer  # noqa: E402
from validate_item29_capacity_100_result_v1 import (  # noqa: E402
    VALIDATOR_REF,
    validate_executor_result,
)


BUILDER_REF = "tools/build_item29_capacity_100_evidence_v1.py"
EXECUTOR_REF = "deploy/production/capacity_100_jobs.py"
RENDERER_REF = "tools/render_item29_capacity_100_request_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
RECEIPT_SCHEMA = "noteai.item29.provider-readback-receipt.v1"
CAPTURE_CONTRACT = "noteai.item29.root-only-provider-raw-closure.v1"
MAX_RAW_BYTES = 4 * 1024 * 1024
PAGE_SIZE = 50
ROOT_UID = 0
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
RAW_PROVIDER_RESPONSE_FILES = (
    "run-command-response.json",
    "pre-describe-commands.json",
    "pre-describe-invocations.json",
    "terminal-describe-commands.json",
    "terminal-describe-invocations.json",
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


class EvidenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ROOT_ONLY_CAPTURE_TOKEN = object()


def _stable(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
    )


class RootOnlyCapture:
    """Opaque raw-capture closure constructible only by the strict loader."""

    __slots__ = (
        "_files", "capture_manifest", "capture_manifest_sha256",
        "raw_provider_bodies_retained_root_only",
        "raw_provider_value_emitted_count",
    )

    def __init__(
        self,
        files: dict[str, bytes],
        security_evidence: dict[str, Any],
        *,
        token: object,
    ) -> None:
        if token is not _ROOT_ONLY_CAPTURE_TOKEN:
            raise EvidenceError("capture_loader_required")
        expected_security = {
            "directory": {
                "mode": "0700",
                "owner_uid": ROOT_UID,
                "nofollow_open": True,
                "stable_before_fd_after": True,
            },
            "files": [
                {
                    "name": name,
                    "mode": "0600",
                    "owner_uid": ROOT_UID,
                    "nlink": 1,
                    "nofollow_open": True,
                    "stable_before_fd_after": True,
                }
                for name in CAPTURE_FILES
            ],
            "exact_inventory": list(CAPTURE_FILES),
        }
        if not _strict(security_evidence, expected_security):
            raise EvidenceError("capture_security_evidence")
        self._files = {name: files[name] for name in CAPTURE_FILES}
        self.capture_manifest = _canonical({
            "capture_contract": CAPTURE_CONTRACT,
            "security": security_evidence,
            "files": [
                {
                    "name": name,
                    "bytes": len(self._files[name]),
                    "sha256": _sha(self._files[name]),
                }
                for name in CAPTURE_FILES
            ],
        })
        self.capture_manifest_sha256 = _sha(self.capture_manifest)
        self.raw_provider_bodies_retained_root_only = (
            _strict(security_evidence, expected_security)
        )
        self.raw_provider_value_emitted_count = 0

    def __getitem__(self, name: str) -> bytes:
        if name not in CAPTURE_FILES:
            raise EvidenceError("capture_file_name")
        return self._files[name]


def _validate_capture_directory(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != ROOT_UID
    ):
        raise EvidenceError("capture_directory_identity")


def _validate_capture_file(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != ROOT_UID
        or row.st_nlink != 1
    ):
        raise EvidenceError("capture_file_identity")


def _read_capture_file(
    directory_fd: int,
    name: str,
) -> tuple[bytes, dict[str, Any]]:
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _validate_capture_file(before)
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        _validate_capture_file(opened)
        raw = b""
        while len(raw) <= MAX_RAW_BYTES:
            chunk = os.read(
                descriptor, min(65536, MAX_RAW_BYTES + 1 - len(raw))
            )
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    stable = (
        _stable(before) == _stable(opened)
        and _stable(opened) == _stable(closed)
        and _stable(closed) == _stable(after)
    )
    if (
        not 1 <= len(raw) <= MAX_RAW_BYTES
        or not stable
    ):
        raise EvidenceError("capture_file_unstable")
    return raw, {
        "name": name,
        "mode": f"{stat.S_IMODE(opened.st_mode):04o}",
        "owner_uid": opened.st_uid,
        "nlink": opened.st_nlink,
        "nofollow_open": bool(os.O_NOFOLLOW),
        "stable_before_fd_after": stable,
    }


def load_root_only_capture(capture_dir: Path) -> RootOnlyCapture:
    """Load the exact root-owned capture without following any path link."""

    if not isinstance(capture_dir, Path) or not capture_dir.is_absolute():
        raise EvidenceError("capture_directory_absolute")
    try:
        before = capture_dir.lstat()
        _validate_capture_directory(before)
        directory_fd = os.open(
            capture_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(directory_fd)
            _validate_capture_directory(opened)
            if _stable(before) != _stable(opened):
                raise EvidenceError("capture_directory_unstable")
            inventory_before = os.listdir(directory_fd)
            if (
                len(inventory_before) != len(CAPTURE_FILES)
                or set(inventory_before) != set(CAPTURE_FILES)
            ):
                raise EvidenceError("capture_files")
            loaded = {
                name: _read_capture_file(directory_fd, name)
                for name in CAPTURE_FILES
            }
            inventory_after = os.listdir(directory_fd)
            closed = os.fstat(directory_fd)
        finally:
            os.close(directory_fd)
        after = capture_dir.lstat()
    except EvidenceError:
        raise
    except OSError as exc:
        raise EvidenceError("capture_read") from exc
    directory_stable = (
        _stable(before) == _stable(opened)
        and _stable(opened) == _stable(closed)
        and _stable(closed) == _stable(after)
    )
    if (
        len(inventory_after) != len(inventory_before)
        or set(inventory_after) != set(inventory_before)
        or not directory_stable
    ):
        raise EvidenceError("capture_directory_unstable")
    return RootOnlyCapture(
        {name: loaded[name][0] for name in CAPTURE_FILES},
        {
            "directory": {
                "mode": f"{stat.S_IMODE(opened.st_mode):04o}",
                "owner_uid": opened.st_uid,
                "nofollow_open": bool(os.O_NOFOLLOW),
                "stable_before_fd_after": directory_stable,
            },
            "files": [loaded[name][1] for name in CAPTURE_FILES],
            "exact_inventory": list(CAPTURE_FILES),
        },
        token=_ROOT_ONLY_CAPTURE_TOKEN,
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _commit(label: str, value: str) -> str:
    if type(value) is not str or not value:
        raise EvidenceError(label)
    return _sha(
        b"noteai-item29-provider-commitment-v1\x00"
        + label.encode("ascii") + b"\x00" + value.encode("utf-8")
    )


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError("duplicate_json_key")
        value[key] = item
    return value


def _json(raw: bytes, label: str, *, canonical: bool = False) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RAW_BYTES or b"\x00" in raw:
        raise EvidenceError(label + "_shape")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(label + "_json") from exc
    if type(value) is not dict:
        raise EvidenceError(label + "_object")
    if canonical and _canonical(value) != raw:
        raise EvidenceError(label + "_canonical")
    return value


def _canonical(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) in {list, tuple}:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise EvidenceError(label)
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise EvidenceError(label)
    return value


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or UTC.fullmatch(value) is None:
        raise EvidenceError(label)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise EvidenceError(label) from exc


def _page(body: Any, container: str, item: str, expected_total: int, label: str):
    if type(body) is not dict or not {
        "RequestId", "PageNumber", "PageSize", "TotalCount", container,
    }.issubset(body):
        raise EvidenceError(label + "_schema")
    wrapper = body[container]
    if type(wrapper) is not dict or set(wrapper) != {item}:
        raise EvidenceError(label + "_wrapper")
    rows = wrapper[item]
    if (
        type(rows) is not list
        or any(type(row) is not dict for row in rows)
        or _integer(body["PageNumber"], label + "_page") != 1
        or _integer(body["PageSize"], label + "_size") != PAGE_SIZE
        or _integer(body["TotalCount"], label + "_total") != expected_total
        or len(rows) != expected_total
    ):
        raise EvidenceError(label + "_incomplete_page")
    return _string(body["RequestId"], label + "_request_id"), rows


def _source(root: Path, ref: str) -> dict[str, Any]:
    raw = (root / ref).read_bytes()
    return {"path": ref, "bytes": len(raw), "sha256": _sha(raw)}


def terminal_acceptance_sha256(value: Any) -> str:
    projection = {
        "schema": value.get("schema") if type(value) is dict else None,
        "task_id": value.get("task_id") if type(value) is dict else None,
        "status": value.get("status") if type(value) is dict else None,
        "source_revision": value.get("source_revision") if type(value) is dict else None,
        "result_binding": value.get("result_binding") if type(value) is dict else None,
        "terminal_readback": value.get("terminal_readback") if type(value) is dict else None,
        "raw_closure": value.get("raw_closure") if type(value) is dict else None,
        "execution_boundary": (
            value.get("execution_boundary") if type(value) is dict else None
        ),
    }
    return _sha(_canonical(projection)[:-1])


def build_receipt(
    capture: RootOnlyCapture,
    *,
    source_revision: str,
    observed_at_utc: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    if type(capture) is not RootOnlyCapture:
        raise EvidenceError("capture_loader_required")
    if type(source_revision) is not str or HEX40.fullmatch(source_revision) is None:
        raise EvidenceError("source_revision")
    observed = _utc(observed_at_utc, "observed_at_utc")
    renderer_input = _json(
        capture["renderer-input.json"], "renderer_input", canonical=True
    )
    request = _json(
        capture["run-command-request.json"], "run_request", canonical=True
    )
    try:
        expected_request, request_validation = renderer.render_request(
            renderer_input, root=root
        )
    except Exception as exc:
        raise EvidenceError("renderer_binding") from exc
    if not _strict(request, expected_request):
        raise EvidenceError("run_request_binding")
    run = _json(capture["run-command-response.json"], "run_response")
    if not {"RequestId", "CommandId", "InvokeId"}.issubset(run):
        raise EvidenceError("run_response_schema")
    run_request_id = _string(run["RequestId"], "run_request_id")
    command_id = _string(run["CommandId"], "command_id")
    invoke_id = _string(run["InvokeId"], "invoke_id")
    target = request["InstanceId"][0]

    page = {"PageNumber": 1, "PageSize": PAGE_SIZE}
    expected_requests = {
        "pre-describe-commands-request.json": {
            "RegionId": renderer.REGION,
            "Name": renderer.COMMAND_NAME,
            **page,
        },
        "pre-describe-invocations-request.json": {
            "RegionId": renderer.REGION,
            "CommandName": renderer.COMMAND_NAME,
            **page,
        },
        "terminal-describe-commands-request.json": {
            "RegionId": renderer.REGION,
            "CommandId": command_id,
            "Name": renderer.COMMAND_NAME,
            **page,
        },
        "terminal-describe-invocations-request.json": {
            "RegionId": renderer.REGION,
            "CommandId": command_id,
            "InvokeId": invoke_id,
            "InstanceId": target,
            **page,
        },
        "terminal-describe-results-request.json": {
            "RegionId": renderer.REGION,
            "CommandId": command_id,
            "InvokeId": invoke_id,
            "InstanceId": target,
            **page,
        },
    }
    for name, expected in expected_requests.items():
        observed_request = _json(capture[name], name, canonical=True)
        if not _strict(observed_request, expected) or "ClientToken" in observed_request:
            raise EvidenceError(name + "_binding")

    pre_commands_id, pre_commands = _page(
        _json(capture["pre-describe-commands.json"], "pre_commands"),
        "Commands", "Command", 0, "pre_commands",
    )
    pre_invocations_id, pre_invocations = _page(
        _json(capture["pre-describe-invocations.json"], "pre_invocations"),
        "Invocations", "Invocation", 0, "pre_invocations",
    )
    if pre_commands or pre_invocations:
        raise EvidenceError("name_history_nonzero")
    terminal_commands_id, commands = _page(
        _json(capture["terminal-describe-commands.json"], "terminal_commands"),
        "Commands", "Command", 1, "terminal_commands",
    )
    command = commands[0]
    readable_command = {
        "CommandId": command_id,
        "Name": renderer.COMMAND_NAME,
        "Type": request["Type"],
        "CommandContent": request["CommandContent"],
        "Timeout": request["Timeout"],
        "WorkingDir": request["WorkingDir"],
        "EnableParameter": request["EnableParameter"],
    }
    command_projection = {
        key: command.get(key) for key in readable_command
    }
    if not _strict(command_projection, readable_command):
        raise EvidenceError("terminal_command")
    terminal_invocations_id, invocations = _page(
        _json(capture["terminal-describe-invocations.json"], "terminal_invocations"),
        "Invocations", "Invocation", 1, "terminal_invocations",
    )
    invocation = invocations[0]
    instances = (invocation.get("InvokeInstances") or {}).get("InvokeInstance")
    if type(instances) is not list or len(instances) != 1:
        raise EvidenceError("terminal_instances")
    instance = instances[0]
    invocation_projection = {
        "CommandId": invocation.get("CommandId"),
        "InvokeId": invocation.get("InvokeId"),
        "CommandName": invocation.get("CommandName"),
        "InvokeStatus": invocation.get("InvokeStatus"),
        "InvocationStatus": invocation.get("InvocationStatus"),
        "RepeatMode": invocation.get("RepeatMode"),
        "Username": invocation.get("Username"),
        "TerminationMode": invocation.get("TerminationMode"),
        "instance": {
            "InstanceId": instance.get("InstanceId"),
            "InstanceInvokeStatus": instance.get("InstanceInvokeStatus"),
            "InvocationStatus": instance.get("InvocationStatus"),
            "ExitCode": instance.get("ExitCode"),
            "Dropped": instance.get("Dropped"),
            "Repeats": instance.get("Repeats"),
        },
    }
    expected_invocation_projection = {
        "CommandId": command_id,
        "InvokeId": invoke_id,
        "CommandName": renderer.COMMAND_NAME,
        "InvokeStatus": "Finished",
        "InvocationStatus": "Success",
        "RepeatMode": "Once",
        "Username": "root",
        "TerminationMode": "ProcessTree",
        "instance": {
            "InstanceId": target,
            "InstanceInvokeStatus": "Finished",
            "InvocationStatus": "Success",
            "ExitCode": 0,
            "Dropped": 0,
            "Repeats": 1,
        },
    }
    if not _strict(invocation_projection, expected_invocation_projection):
        raise EvidenceError("terminal_invocation")

    results_body = _json(capture["terminal-describe-results.json"], "terminal_results")
    results_request_id = _string(results_body.get("RequestId"), "results_request_id")
    result_invocation = results_body.get("Invocation")
    if type(result_invocation) is not dict:
        raise EvidenceError("result_invocation")
    result_rows = (result_invocation.get("InvocationResults") or {}).get(
        "InvocationResult"
    )
    if (
        type(result_rows) is not list
        or len(result_rows) != 1
        or _integer(result_invocation.get("PageNumber"), "result_page_number")
        != 1
        or _integer(result_invocation.get("PageSize"), "result_page_size")
        != PAGE_SIZE
        or _integer(result_invocation.get("TotalCount"), "result_total_count")
        != 1
    ):
        raise EvidenceError("result_page")
    provider_result = result_rows[0]
    start = _utc(provider_result.get("StartTime"), "result_start")
    finished = _utc(provider_result.get("FinishedTime"), "result_finished")
    result_projection = {
        "CommandId": provider_result.get("CommandId"),
        "InvokeId": provider_result.get("InvokeId"),
        "InstanceId": provider_result.get("InstanceId"),
        "InvocationStatus": provider_result.get("InvocationStatus"),
        "ExitCode": provider_result.get("ExitCode"),
        "Dropped": provider_result.get("Dropped"),
        "Repeats": provider_result.get("Repeats"),
    }
    if (
        not _strict(result_projection, {
            "CommandId": command_id,
            "InvokeId": invoke_id,
            "InstanceId": target,
            "InvocationStatus": "Success",
            "ExitCode": 0,
            "Dropped": 0,
            "Repeats": 1,
        })
        or provider_result.get("ErrorCode") not in {None, ""}
        or provider_result.get("ErrorInfo") not in {None, ""}
        or not start < finished <= observed
    ):
        raise EvidenceError("provider_result")
    try:
        stdout = base64.b64decode(
            _string(provider_result.get("Output"), "result_output").encode("ascii"),
            validate=True,
        )
        result = json.loads(stdout.decode("ascii"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("result_output") from exc
    if _canonical(result) != stdout:
        raise EvidenceError("result_canonical")
    result_errors, result_binding = validate_executor_result(result)
    if result_errors or result_binding is None:
        raise EvidenceError("result_semantics")
    request_ids = {
        run_request_id, pre_commands_id, pre_invocations_id,
        terminal_commands_id, terminal_invocations_id, results_request_id,
    }
    if len(request_ids) != 6:
        raise EvidenceError("request_id_uniqueness")
    receipt = {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "action": renderer.ACTION,
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "observed_at_utc": observed_at_utc,
        "source_revision": source_revision,
        "source_binding": {
            "executor": _source(root, EXECUTOR_REF),
            "renderer": _source(root, RENDERER_REF),
            "builder": _source(root, BUILDER_REF),
            "validator": _source(root, VALIDATOR_REF),
        },
        "item28_dependency": result["item28_dependency"],
        "raw_closure": {
            "capture_contract": CAPTURE_CONTRACT,
            "capture_file_count": len(CAPTURE_FILES),
            "capture_manifest_canonical_bytes": len(capture.capture_manifest),
            "capture_manifest_sha256": capture.capture_manifest_sha256,
            "raw_provider_response_count": len(RAW_PROVIDER_RESPONSE_FILES),
            "provider_request_count": len(PROVIDER_REQUEST_FILES),
            "raw_provider_bodies_retained_root_only": (
                capture.raw_provider_bodies_retained_root_only
            ),
            "raw_provider_value_emitted_count": (
                capture.raw_provider_value_emitted_count
            ),
        },
        "request": {
            "command_name": renderer.COMMAND_NAME,
            "request_sha256": _sha(capture["run-command-request.json"]),
            "client_token_commitment_sha256": _commit(
                "client-token", request["ClientToken"]
            ),
            "target_commitment_sha256": _commit("target", target),
            "command_id_commitment_sha256": _commit("command", command_id),
            "invoke_id_commitment_sha256": _commit("invoke", invoke_id),
        },
        "pre_dispatch": {
            "history_key": "Name",
            "all_pages": True,
            "exact_command_name_history_count": 0,
            "exact_invocation_name_history_count": 0,
            "provider_client_token_readback_supported": False,
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
        },
        "result": result,
        "result_binding": result_binding,
        "execution_boundary": {
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
        },
    }
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(receipt)
    return receipt


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        capture_dir = args.capture_dir
        if not capture_dir.is_absolute():
            raise EvidenceError("capture_directory_absolute")
        closure = load_root_only_capture(capture_dir)
        receipt = build_receipt(
            closure,
            source_revision=args.source_revision,
            observed_at_utc=args.observed_at_utc,
            root=args.root,
        )
        output = _canonical(receipt)
        if args.output is None:
            sys.stdout.buffer.write(output)
        else:
            if not args.output.is_absolute():
                raise EvidenceError("output_absolute")
            _write_exclusive(args.output, output)
    except (EvidenceError, OSError) as exc:
        code = exc.code if isinstance(exc, EvidenceError) else "output_write"
        sys.stderr.write(code + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
