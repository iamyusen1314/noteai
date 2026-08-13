#!/usr/bin/env python3
"""Bind Item 26 command bytes to the fixed Cloud Assistant requests.

This module is a local, Secret-free request renderer.  It performs no provider
read or write and deliberately supplies no generic retry or dispatch helper.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re
import sys
from types import MappingProxyType


REGION = "cn-shenzhen"
TASK_TAG = ({"Key": "noteai-task", "Value": "item26-restored-v1"},)
MAX_INPUT_BYTES = 65536
MAX_COMMAND_CONTENT_BYTES = 18000
MAX_SEND_FILE_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")
PLAN_NONCE = re.compile(r"^[0-9a-f]{32}$")
COMMAND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RequestError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Action:
    name: str
    target: str
    timeout: int
    prerequisites: tuple[str, ...]
    terminal_recovery: str


_ACTION_ROWS = (
    (
        "preflight_api_c",
        "noteai-item26-restored-preflight-api-c-20260813-v2",
        "api_c",
        120,
        ("EXACT_CHECKPOINT_CI_GREEN", "FRESH_CLOUD_BASELINE_PASS"),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "preflight_builder",
        "noteai-item26-restored-preflight-builder-20260813-v2",
        "builder",
        120,
        ("API_C_PREFLIGHT_PASS", "BUILDER_RUNNING_AGENT_READY_ROLE_EXACT"),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "keygen_generate",
        "noteai-item26-restored-keygen-generate-20260813-v2",
        "builder",
        120,
        ("BUILDER_PREFLIGHT_PASS",),
        "DISPATCH_keygen_readback_ONLY_AFTER_TERMINAL_UNKNOWN",
    ),
    (
        "keygen_readback",
        "noteai-item26-restored-keygen-readback-20260813-v2",
        "builder",
        120,
        ("KEYGEN_GENERATE_TERMINAL_UNKNOWN",),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "password_rewrap_create",
        "noteai-item26-restored-password-rewrap-create-20260813-v2",
        "api_c",
        120,
        ("API_C_PREFLIGHT_PASS", "KEYGEN_PASS"),
        "DISPATCH_password_rewrap_readback_ONLY_AFTER_TERMINAL_UNKNOWN",
    ),
    (
        "password_rewrap_readback",
        "noteai-item26-restored-password-rewrap-readback-20260813-v2",
        "api_c",
        120,
        ("PASSWORD_REWRAP_CREATE_TERMINAL_UNKNOWN",),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "package_broker_create",
        "noteai-item26-restored-package-broker-create-20260813-v2",
        "api_c",
        120,
        ("API_C_PREFLIGHT_PASS", "PASSWORD_REWRAP_PASS"),
        "DISPATCH_package_broker_readback_EXACTLY_ONCE_AFTER_EXIT_0_OR_4",
    ),
    (
        "package_broker_readback",
        "noteai-item26-restored-package-broker-readback-20260813-v2",
        "api_c",
        120,
        ("PACKAGE_BROKER_CREATE_EXIT_0_OR_4",),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "builder_stage_finalize",
        "noteai-item26-restored-builder-stage-finalize-20260813-v2",
        "builder",
        120,
        ("PACKAGE_BROKER_READBACK_PASS", "TWO_SEND_FILES_TERMINAL_SUCCESS"),
        "DISPATCH_builder_stage_readback_ONLY_AFTER_TERMINAL_UNKNOWN",
    ),
    (
        "builder_stage_readback",
        "noteai-item26-restored-builder-stage-readback-20260813-v2",
        "builder",
        120,
        ("BUILDER_STAGE_FINALIZE_TERMINAL_UNKNOWN",),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
    (
        "restored_capture",
        "noteai-item26-restored-capture-20260813-v2",
        "builder",
        1500,
        ("BUILDER_STAGE_PASS", "FRESH_RESTORED_DATABASE_BASELINE_PASS"),
        "STOP_RETAIN_MATERIAL_NEVER_REPLAY",
    ),
)

ACTIONS = MappingProxyType({
    key: Action(name, target, timeout, prerequisites, recovery)
    for key, name, target, timeout, prerequisites, recovery in _ACTION_ROWS
})
ACTION_ORDER = tuple(row[0] for row in _ACTION_ROWS)
TERMINAL_TRANSITIONS = MappingProxyType({
    "preflight_api_c": MappingProxyType({
        "0": "API_C_PREFLIGHT_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "preflight_builder": MappingProxyType({
        "0": "BUILDER_PREFLIGHT_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "keygen_generate": MappingProxyType({
        "0": "KEYGEN_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "DISPATCH_keygen_readback_ONCE",
    }),
    "keygen_readback": MappingProxyType({
        "0": "KEYGEN_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "password_rewrap_create": MappingProxyType({
        "0": "PASSWORD_REWRAP_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "DISPATCH_password_rewrap_readback_ONCE",
    }),
    "password_rewrap_readback": MappingProxyType({
        "0": "PASSWORD_REWRAP_PASS",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "package_broker_create": MappingProxyType({
        "0": "DISPATCH_package_broker_readback_ONCE",
        "3": "STOP_KNOWN_FAIL",
        "4": "DISPATCH_package_broker_readback_ONCE",
    }),
    "package_broker_readback": MappingProxyType({
        "0": "POST_BROKER_ALLOWED",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "builder_stage_finalize": MappingProxyType({
        "0": "BUILDER_STAGE_PASS_CAPTURE_ALLOWED",
        "3": "STOP_KNOWN_FAIL",
        "4": "DISPATCH_builder_stage_readback_ONCE",
    }),
    "builder_stage_readback": MappingProxyType({
        "0": "INSPECT_RESULT_ONLY_STAGE_PASS_ALLOWS_CAPTURE",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
    "restored_capture": MappingProxyType({
        "0": "RECONCILE_CAPTURE_RESULT",
        "3": "STOP_KNOWN_FAIL",
        "4": "STOP_CONNECTED_UNKNOWN_RETAIN_NEVER_REPLAY",
    }),
})

SEND_FILE_TARGETS = MappingProxyType({
    "control-envelope.json": "/var/lib/noteai/item26-restored-v1/control",
    "restored-capture-transfer-v1.sh.gz": "/var/lib/noteai/item26-restored-v1",
})
SEND_FILE_ORDER = tuple(SEND_FILE_TARGETS)

RUN_COMMAND_KEYS = frozenset({
    "ClientToken",
    "CommandContent",
    "ContentEncoding",
    "EnableParameter",
    "InstanceId",
    "KeepCommand",
    "Name",
    "RegionId",
    "RepeatMode",
    "Tag",
    "TerminationMode",
    "Timeout",
    "Type",
    "Username",
    "WorkingDir",
})

SEND_FILE_KEYS = frozenset({
    "Content",
    "ContentType",
    "Description",
    "FileGroup",
    "FileMode",
    "FileOwner",
    "InstanceId",
    "Name",
    "Overwrite",
    "RegionId",
    "Tag",
    "TargetDir",
})


def canonical(value):
    try:
        return (json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RequestError("input_json") from exc


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestError("duplicate_json_key")
        result[key] = value
    return result


def parse_canonical(raw):
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_INPUT_BYTES
        or not raw.endswith(b"\n")
        or b"\r" in raw
        or b"\x00" in raw
    ):
        raise RequestError("input_shape")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_no_duplicates)
    except RequestError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequestError("input_json") from exc
    if type(value) is not dict or canonical(value) != raw:
        raise RequestError("input_canonical")
    return value


def _valid_instance(value, label):
    if type(value) is not str or INSTANCE_ID.fullmatch(value) is None:
        raise RequestError(label)
    return value


def derive_client_tokens(plan_nonce):
    if type(plan_nonce) is not str or PLAN_NONCE.fullmatch(plan_nonce) is None:
        raise RequestError("plan_nonce")
    prefix = b"item26-restored-v1\x00" + plan_nonce.encode("ascii") + b"\x00"
    tokens = {
        action: hashlib.sha256(prefix + action.encode("ascii")).hexdigest()
        for action in ACTION_ORDER
    }
    if (
        tuple(tokens) != ACTION_ORDER
        or set(tokens) != set(ACTIONS)
        or len(set(tokens.values())) != len(ACTION_ORDER)
        or any(HEX64.fullmatch(value) is None for value in tokens.values())
    ):
        raise RequestError("client_token_plan")
    return tokens


def _valid_sha256(value, label):
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise RequestError(label)
    return value


def _decode_canonical_base64(value, label):
    if type(value) is not str or not value or not value.isascii():
        raise RequestError(label)
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(encoded, validate=True)
    except (UnicodeError, ValueError) as exc:
        raise RequestError(label) from exc
    if not raw or base64.b64encode(raw) != encoded:
        raise RequestError(label)
    return encoded, raw


def _command(value):
    if type(value) is not dict or set(value) != {"base64", "bytes", "sha256"}:
        raise RequestError("command_contract")
    encoded, _ = _decode_canonical_base64(value["base64"], "command_base64")
    if len(encoded) > MAX_COMMAND_CONTENT_BYTES:
        raise RequestError("command_limit")
    if type(value["bytes"]) is not int or value["bytes"] != len(encoded):
        raise RequestError("command_bytes")
    digest = _valid_sha256(value["sha256"], "command_sha256")
    if digest != hashlib.sha256(encoded).hexdigest():
        raise RequestError("command_sha256")
    return encoded.decode("ascii"), digest


def _input(value):
    expected = {
        "action",
        "api_c_instance_id",
        "builder_instance_id",
        "command",
        "plan_nonce",
    }
    if type(value) is not dict or set(value) != expected:
        raise RequestError("input_contract")
    action = value["action"]
    if type(action) is not str or action not in ACTIONS:
        raise RequestError("action")
    api_c = _valid_instance(value["api_c_instance_id"], "api_c_instance_id")
    builder = _valid_instance(value["builder_instance_id"], "builder_instance_id")
    if api_c == builder:
        raise RequestError("instance_distinct")
    tokens = derive_client_tokens(value["plan_nonce"])
    content, digest = _command(value["command"])
    return action, api_c, builder, tokens, content, digest


def _expected_request(value):
    action, api_c, builder, tokens, content, digest = _input(value)
    spec = ACTIONS[action]
    target = api_c if spec.target == "api_c" else builder
    request = {
        "ClientToken": tokens[action],
        "CommandContent": content,
        "ContentEncoding": "Base64",
        "EnableParameter": False,
        "InstanceId": [target],
        "KeepCommand": True,
        "Name": spec.name,
        "RegionId": REGION,
        "RepeatMode": "Once",
        "Tag": [dict(TASK_TAG[0])],
        "TerminationMode": "ProcessTree",
        "Timeout": spec.timeout,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    return action, spec, target, request, digest, tokens


def validate_run_command(request, input_value):
    action, spec, target, expected, digest, _ = _expected_request(input_value)
    if type(request) is not dict or set(request) != RUN_COMMAND_KEYS:
        raise RequestError("run_command_contract")
    if request != expected:
        raise RequestError("run_command_binding")
    if (
        type(request["KeepCommand"]) is not bool
        or request["KeepCommand"] is not True
        or type(request["EnableParameter"]) is not bool
        or request["EnableParameter"] is not False
        or type(request["Timeout"]) is not int
        or request["Timeout"] != spec.timeout
        or type(request["InstanceId"]) is not list
        or len(request["InstanceId"]) != 1
        or request["InstanceId"][0] != target
        or type(request["Name"]) is not str
        or COMMAND_NAME.fullmatch(request["Name"]) is None
    ):
        raise RequestError("run_command_types")
    return {"action": action, "command_content_sha256": digest}


def render_request(value):
    action, spec, target, request, digest, tokens = _expected_request(value)
    validate_run_command(request, value)
    request_raw = canonical(request)
    return {
        "action": action,
        "evidence": {
            "command_content_base64_bytes": len(request["CommandContent"].encode("ascii")),
            "command_content_sha256": digest,
            "client_token_plan_count": len(tokens),
            "client_token_plan_sha256": hashlib.sha256(canonical(tokens)).hexdigest(),
            "request_canonical_bytes": len(request_raw),
            "request_canonical_sha256": hashlib.sha256(request_raw).hexdigest(),
        },
        "prerequisites": {
            "action_prerequisites": list(spec.prerequisites),
            "fresh_client_token_history_count_must_equal": 0,
            "fresh_exact_name_target_history_count_must_equal": 0,
            "plan_nonce_emitted_by_renderer": False,
            "plan_nonce_must_be_retained_root_only": True,
            "provider_reads_performed_by_renderer": 0,
        },
        "request": request,
        "state": {
            "automatic_retry_allowed": False,
            "dispatch_count_limit": 1,
            "initial": "HISTORY_ZERO_REQUIRED",
            "post_submit": "PROVIDER_READBACK_ONLY",
            "provider_unknown_recovery": (
                "READBACK_EXACT_CLIENT_TOKEN_NAME_TARGET_NEVER_RESUBMIT"
            ),
            "same_request_resubmit_allowed": False,
            "terminal_exit_code": dict(TERMINAL_TRANSITIONS[action]),
            "terminal_command_recovery": spec.terminal_recovery,
        },
    }


def validate_send_file(request, evidence, builder_instance_id):
    builder = _valid_instance(builder_instance_id, "builder_instance_id")
    if type(request) is not dict or set(request) != SEND_FILE_KEYS:
        raise RequestError("send_file_contract")
    if type(evidence) is not dict or set(evidence) != {
        "content_base64_bytes",
        "content_sha256",
    }:
        raise RequestError("send_file_evidence_contract")
    name = request.get("Name")
    if type(name) is not str or name not in SEND_FILE_TARGETS:
        raise RequestError("send_file_name")
    expected = {
        "Content": request.get("Content"),
        "ContentType": "Base64",
        "Description": "noteai-item26-restored-v1-write-once",
        "FileGroup": "root",
        "FileMode": "0600",
        "FileOwner": "root",
        "InstanceId": [builder],
        "Name": name,
        "Overwrite": False,
        "RegionId": REGION,
        "Tag": [dict(TASK_TAG[0])],
        "TargetDir": SEND_FILE_TARGETS[name],
    }
    if request != expected:
        raise RequestError("send_file_binding")
    if type(request["Overwrite"]) is not bool or request["Overwrite"] is not False:
        raise RequestError("send_file_overwrite")
    encoded, raw = _decode_canonical_base64(request["Content"], "send_file_content")
    if len(encoded) > MAX_SEND_FILE_CONTENT_BYTES:
        raise RequestError("send_file_content")
    if (
        type(evidence["content_base64_bytes"]) is not int
        or evidence["content_base64_bytes"] != len(encoded)
    ):
        raise RequestError("send_file_evidence_bytes")
    digest = _valid_sha256(evidence["content_sha256"], "send_file_evidence_sha256")
    if digest != hashlib.sha256(raw).hexdigest():
        raise RequestError("send_file_evidence_sha256")
    request_raw = canonical(request)
    return {
        "content_base64_bytes": len(encoded),
        "content_sha256": digest,
        "content_sha256_scope": "decoded_raw_bytes",
        "name": name,
        "no_replay": {
            "describe_all_pages_required": True,
            "exact_name_required": True,
            "history_zero_required": True,
            "overwrite_must_be_false": True,
            "provider_ack_unknown_allowed_action": (
                "DESCRIBE_EXACT_NAME_INSTANCE_ALL_PAGES"
            ),
            "send_file_has_client_token": False,
            "unknown_recovery": (
                "DESCRIBE_EXACT_NAME_INSTANCE_ALL_PAGES_NEVER_RESEND"
            ),
        },
        "request_canonical_bytes": len(request_raw),
        "request_canonical_sha256": hashlib.sha256(request_raw).hexdigest(),
        "target_instance_count": 1,
    }


def validate_send_file_plan(rows, builder_instance_id):
    builder = _valid_instance(builder_instance_id, "builder_instance_id")
    if type(rows) is not list or len(rows) != len(SEND_FILE_ORDER):
        raise RequestError("send_file_plan_contract")
    results = []
    for index, expected_name in enumerate(SEND_FILE_ORDER):
        row = rows[index]
        if type(row) is not dict or set(row) != {"evidence", "request"}:
            raise RequestError("send_file_plan_row")
        request = row["request"]
        if type(request) is not dict or request.get("Name") != expected_name:
            raise RequestError("send_file_plan_order")
        results.append(validate_send_file(request, row["evidence"], builder))
    names = tuple(result["name"] for result in results)
    if names != SEND_FILE_ORDER or len(set(names)) != len(SEND_FILE_ORDER):
        raise RequestError("send_file_plan_order")
    binding = {
        "order": list(names),
        "request_canonical_sha256": [
            result["request_canonical_sha256"] for result in results
        ],
    }
    binding_raw = canonical(binding)
    return {
        "files": results,
        "order": list(names),
        "plan_binding_bytes": len(binding_raw),
        "plan_binding_sha256": hashlib.sha256(binding_raw).hexdigest(),
        "request_count": len(results),
    }


def _validate_static_contract():
    if (
        len(ACTIONS) != 11
        or tuple(ACTIONS) != ACTION_ORDER
        or set(TERMINAL_TRANSITIONS) != set(ACTIONS)
        or len({row.name for row in ACTIONS.values()}) != 11
        or SEND_FILE_ORDER != (
            "control-envelope.json",
            "restored-capture-transfer-v1.sh.gz",
        )
    ):
        raise RuntimeError("invalid action table")
    for row in ACTIONS.values():
        if (
            COMMAND_NAME.fullmatch(row.name) is None
            or row.target not in {"api_c", "builder"}
            or type(row.timeout) is not int
            or row.timeout not in {120, 1500}
        ):
            raise RuntimeError("invalid action row")


def cli():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        result = render_request(parse_canonical(raw))
        output = canonical(result)
    except RequestError as exc:
        sys.stderr.write("ITEM26_RESTORED_CLOUD_REQUEST_FAILED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM26_RESTORED_CLOUD_REQUEST_FAILED:internal\n")
        return 2
    sys.stdout.buffer.write(output)
    return 0


_validate_static_contract()


if __name__ == "__main__":
    raise SystemExit(cli())
