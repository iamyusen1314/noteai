#!/usr/bin/env python3
"""Render the four exact Item 27 Cloud Assistant requests locally.

The renderer reads one frozen, Secret-free executor from the repository and
wraps it in a bounded self-cleaning shell command.  It performs no provider
read or write and intentionally exposes no dispatch or retry helper.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import MappingProxyType


REGION = "cn-shenzhen"
TASK_TAG = ("noteai-task", "item27-internal-smoke-v1")
MAX_INPUT_BYTES = 65536
MAX_COMMAND_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")
PLAN_NONCE = re.compile(r"^[0-9a-f]{32}$")
COMMAND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = "deploy/production/internal_zero_provider_smoke.py"
EXECUTOR_IDENTITY = MappingProxyType({
    "bytes": 31841,
    "sha256": "bc0d6fe3ba6f5d25d908a89a8ecd53d09b427427cdd8a52ed2d42bb3c2d35250",
    "mode": 0o644,
})
PROVIDER_TIMEOUT_SECONDS = MappingProxyType({
    "api-c": 3300,
    "api-f": 2760,
    "worker-c": 1380,
    "worker-f": 1380,
})


class RequestError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Action:
    name: str
    target: str
    host_mode: str
    timeout: int
    prerequisites: tuple[str, ...]


_ACTION_ROWS = (
    (
        "api_c",
        "noteai-item27-internal-smoke-api-c-20260823-stop-status-fix1",
        "api_c_instance_id",
        "api-c",
        PROVIDER_TIMEOUT_SECONDS["api-c"],
        (
            "ITEM26_TERMINAL_PASS",
            "EXACT_CHECKPOINT_CI_GREEN",
            "FRESH_PRIVATE_RUNTIME_BASELINE_PASS",
        ),
    ),
    (
        "api_f",
        "noteai-item27-internal-smoke-api-f-20260823-image-compat-fix1",
        "api_f_instance_id",
        "api-f",
        PROVIDER_TIMEOUT_SECONDS["api-f"],
        ("API_C_INTERNAL_SMOKE_PASS",),
    ),
    (
        "worker_c",
        "noteai-item27-internal-smoke-worker-c-20260813-v1",
        "worker_c_instance_id",
        "worker-c",
        PROVIDER_TIMEOUT_SECONDS["worker-c"],
        ("API_F_INTERNAL_SMOKE_PASS",),
    ),
    (
        "worker_f",
        "noteai-item27-internal-smoke-worker-f-20260813-v1",
        "worker_f_instance_id",
        "worker-f",
        PROVIDER_TIMEOUT_SECONDS["worker-f"],
        ("WORKER_C_INTERNAL_SMOKE_PASS",),
    ),
)

ACTIONS = MappingProxyType({
    key: Action(name, target, host_mode, timeout, prerequisites)
    for key, name, target, host_mode, timeout, prerequisites in _ACTION_ROWS
})
ACTION_ORDER = tuple(row[0] for row in _ACTION_ROWS)
INSTANCE_KEYS = tuple(row[2] for row in _ACTION_ROWS)
PREDECESSOR_ACCEPTANCE_SOURCES = MappingProxyType({
    "api_c": "item26_terminal_acceptance",
    "api_f": "api_c_terminal_acceptance",
    "worker_c": "api_f_terminal_acceptance",
    "worker_f": "worker_c_terminal_acceptance",
})
TERMINAL_TRANSITIONS = MappingProxyType({
    action: MappingProxyType({
        "0": action.upper() + "_INTERNAL_SMOKE_PASS",
        "3": "STOP_KNOWN_FAIL_NEVER_REPLAY",
        "4": "STOP_UNKNOWN_RETAIN_NEVER_REPLAY",
    })
    for action in ACTION_ORDER
})

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


def canonical(value: object) -> bytes:
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


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError("duplicate_json_key")
        result[key] = value
    return result


def parse_canonical(raw: bytes) -> dict[str, object]:
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _valid_instance(value: object, label: str) -> str:
    if type(value) is not str or INSTANCE_ID.fullmatch(value) is None:
        raise RequestError(label)
    return value


def derive_client_tokens(
    plan_nonce: object, predecessor_acceptance_sha256: object
) -> dict[str, str]:
    if type(plan_nonce) is not str or PLAN_NONCE.fullmatch(plan_nonce) is None:
        raise RequestError("plan_nonce")
    if (
        type(predecessor_acceptance_sha256) is not str
        or HEX64.fullmatch(predecessor_acceptance_sha256) is None
    ):
        raise RequestError("predecessor_acceptance_sha256")
    prefix = (
        b"item27-internal-smoke-v1\x00"
        + plan_nonce.encode("ascii")
        + b"\x00"
        + predecessor_acceptance_sha256.encode("ascii")
        + b"\x00"
    )
    tokens = {
        action: _sha256(prefix + action.encode("ascii"))
        for action in ACTION_ORDER
    }
    if (
        tuple(tokens) != ACTION_ORDER
        or len(set(tokens.values())) != len(ACTION_ORDER)
        or any(HEX64.fullmatch(token) is None for token in tokens.values())
    ):
        raise RequestError("client_token_plan")
    return tokens


def _input(
    value: object,
) -> tuple[str, dict[str, str], dict[str, str], str]:
    expected = {
        "action", "plan_nonce", "predecessor_acceptance_sha256",
        *INSTANCE_KEYS,
    }
    if type(value) is not dict or set(value) != expected:
        raise RequestError("input_contract")
    action = value["action"]
    if type(action) is not str or action not in ACTIONS:
        raise RequestError("action")
    instances = {
        key: _valid_instance(value[key], key)
        for key in INSTANCE_KEYS
    }
    if len(set(instances.values())) != len(INSTANCE_KEYS):
        raise RequestError("instances_distinct")
    predecessor = value["predecessor_acceptance_sha256"]
    tokens = derive_client_tokens(value["plan_nonce"], predecessor)
    return action, instances, tokens, predecessor


def _stable_file_identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
    )


def _read_executor() -> bytes:
    expected_bytes = EXECUTOR_IDENTITY["bytes"]
    expected_sha256 = EXECUTOR_IDENTITY["sha256"]
    expected_mode = EXECUTOR_IDENTITY["mode"]
    if (
        type(expected_bytes) is not int
        or type(expected_sha256) is not str
        or type(expected_mode) is not int
        or expected_bytes <= 0
        or HEX64.fullmatch(expected_sha256) is None
        or expected_mode != 0o644
    ):
        raise RequestError("executor_identity_unfrozen")
    path = REPOSITORY_ROOT / EXECUTOR_PATH
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        before = path.lstat()
        descriptor = os.open(str(path), flags)
        try:
            opened = os.fstat(descriptor)
            payload = b""
            while len(payload) <= expected_bytes:
                chunk = os.read(
                    descriptor,
                    min(65536, expected_bytes + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise RequestError("executor_read") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != expected_mode
        or _stable_file_identity(before) != _stable_file_identity(opened)
        or _stable_file_identity(opened) != _stable_file_identity(closed)
        or _stable_file_identity(closed) != _stable_file_identity(after)
        or len(payload) != expected_bytes
        or _sha256(payload) != expected_sha256
    ):
        raise RequestError("executor_identity")
    if (
        b"\x00" in payload
        or b"\r" in payload
        or not payload.endswith(b"\n")
    ):
        raise RequestError("executor_encoding")
    try:
        payload.decode("ascii")
    except UnicodeError as exc:
        raise RequestError("executor_encoding") from exc
    return payload


def _deterministic_gzip(payload: bytes) -> bytes:
    output = io.BytesIO()
    try:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=output,
            mtime=0,
        ) as stream:
            stream.write(payload)
        compressed = bytearray(output.getvalue())
        if len(compressed) < 18:
            raise ValueError("short gzip")
        # The OS byte has no decompression semantics; fixing it removes the
        # only platform header variance in Python's deterministic gzip stream.
        compressed[9] = 255
        result = bytes(compressed)
        if gzip.decompress(result) != payload:
            raise ValueError("gzip roundtrip")
    except BaseException as exc:
        raise RequestError("executor_gzip") from exc
    return result


def _wrapped_lines(payload: bytes, width: int = 76) -> bytes:
    encoded = base64.b64encode(payload)
    if base64.b64decode(encoded, validate=True) != payload:
        raise RequestError("executor_base64")
    return b"\n".join(encoded[index:index + width] for index in range(0, len(encoded), width))


def _render_wrapper(action: str, executor: bytes) -> tuple[bytes, bytes]:
    spec = ACTIONS[action]
    compressed = _deterministic_gzip(executor)
    payload = _wrapped_lines(compressed)
    task_root = "/run/noteai-item27-internal-smoke-v1-" + spec.host_mode
    wrapper = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "umask 077\n"
        "task_root='" + task_root + "'\n"
        "archive=\"$task_root/executor.py.gz\"\n"
        "source_file=\"$task_root/executor.py\"\n"
        "created=0\n"
        "cleanup() {\n"
        "  set +e\n"
        "  test \"$created\" = 1 || return 0\n"
        "  /usr/bin/rm -f -- \"$source_file\" \"$archive\"\n"
        "  /usr/bin/rmdir -- \"$task_root\" 2>/dev/null\n"
        "  test ! -e \"$source_file\" -a ! -L \"$source_file\" -a ! -e \"$archive\" -a ! -L \"$archive\" -a ! -e \"$task_root\" -a ! -L \"$task_root\"\n"
        "}\n"
        "on_exit() {\n"
        "  result=$?\n"
        "  trap - EXIT HUP INT TERM\n"
        "  cleanup >/dev/null 2>&1 || exit 4\n"
        "  case \"$result\" in 0|3|4) exit \"$result\" ;; *) exit 3 ;; esac\n"
        "}\n"
        "on_signal() { exit 4; }\n"
        "trap on_signal HUP INT TERM\n"
        "trap on_exit EXIT\n"
        "if test -e \"$task_root\" -o -L \"$task_root\"; then exit 3; fi\n"
        "/usr/bin/mkdir -m 0700 -- \"$task_root\" || exit 3\n"
        "created=1\n"
        "test \"$(/usr/bin/stat -c '%u:%g:%a' \"$task_root\")\" = '0:0:700' || exit 3\n"
        "/usr/bin/base64 -d >\"$archive\" <<'ITEM27_EXECUTOR_GZIP'\n"
    ).encode("ascii") + payload + (
        "\nITEM27_EXECUTOR_GZIP\n"
        "test \"$(/usr/bin/wc -c <\"$archive\" | /usr/bin/tr -d ' ')\" = '"
        + str(len(compressed)) + "' || exit 3\n"
        "test \"$(/usr/bin/sha256sum \"$archive\" | /usr/bin/cut -d ' ' -f 1)\" = '"
        + _sha256(compressed) + "' || exit 3\n"
        "/usr/bin/gzip -dc -- \"$archive\" >\"$source_file\" || exit 3\n"
        "/usr/bin/chown root:root \"$source_file\"\n"
        "/usr/bin/chmod 0600 \"$source_file\"\n"
        "test \"$(/usr/bin/wc -c <\"$source_file\" | /usr/bin/tr -d ' ')\" = '"
        + str(len(executor)) + "' || exit 3\n"
        "test \"$(/usr/bin/sha256sum \"$source_file\" | /usr/bin/cut -d ' ' -f 1)\" = '"
        + _sha256(executor) + "' || exit 3\n"
        "set +e\n"
        "/usr/bin/python3 -B \"$source_file\" --mode '" + spec.host_mode + "'\n"
        "result=$?\n"
        "set -e\n"
        "case \"$result\" in 0|3|4) ;; *) result=4 ;; esac\n"
        "exit \"$result\"\n"
    ).encode("ascii")
    if (
        not wrapper.endswith(b"\n")
        or b"\r" in wrapper
        or b"\x00" in wrapper
        or wrapper.count(b"ITEM27_EXECUTOR_GZIP") != 2
    ):
        raise RequestError("command_wrapper")
    return wrapper, compressed


def _command_content(wrapper: bytes) -> tuple[str, str]:
    encoded = base64.b64encode(wrapper)
    if (
        base64.b64decode(encoded, validate=True) != wrapper
        or len(encoded) > MAX_COMMAND_CONTENT_BYTES
    ):
        raise RequestError("command_limit")
    return encoded.decode("ascii"), _sha256(encoded)


def _expected_request(value: object):
    action, instances, tokens, predecessor = _input(value)
    executor = _read_executor()
    wrapper, compressed = _render_wrapper(action, executor)
    content, content_sha256 = _command_content(wrapper)
    spec = ACTIONS[action]
    target = instances[spec.target]
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
        "Tag": [{"Key": TASK_TAG[0], "Value": TASK_TAG[1]}],
        "TerminationMode": "ProcessTree",
        "Timeout": spec.timeout,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    return (
        action,
        spec,
        target,
        request,
        tokens,
        executor,
        compressed,
        wrapper,
        content_sha256,
        predecessor,
    )


def validate_run_command(request: object, input_value: object) -> dict[str, object]:
    (
        action, spec, target, expected, _, executor, _, wrapper, digest,
        predecessor,
    ) = _expected_request(input_value)
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
    return {
        "action": action,
        "command_content_sha256": digest,
        "executor_sha256": _sha256(executor),
        "wrapper_sha256": _sha256(wrapper),
        "predecessor_acceptance_sha256": predecessor,
    }


def render_request(value: object) -> dict[str, object]:
    (
        action,
        spec,
        _,
        request,
        tokens,
        executor,
        compressed,
        wrapper,
        content_sha256,
        predecessor,
    ) = _expected_request(value)
    validate_run_command(request, value)
    request_raw = canonical(request)
    return {
        "action": action,
        "evidence": {
            "command_content_base64_bytes": len(request["CommandContent"].encode("ascii")),
            "command_content_sha256": content_sha256,
            "compressed_executor_bytes": len(compressed),
            "compressed_executor_sha256": _sha256(compressed),
            "executor_bytes": len(executor),
            "executor_path": EXECUTOR_PATH,
            "executor_sha256": _sha256(executor),
            "request_canonical_bytes": len(request_raw),
            "request_canonical_sha256": _sha256(request_raw),
            "predecessor_acceptance_sha256": predecessor,
            "predecessor_acceptance_source": (
                PREDECESSOR_ACCEPTANCE_SOURCES[action]
            ),
            "token_plan_count": len(tokens),
            "token_plan_sha256": _sha256(canonical(tokens)),
            "wrapper_bytes": len(wrapper),
            "wrapper_sha256": _sha256(wrapper),
        },
        "prerequisites": {
            "action_prerequisites": list(spec.prerequisites),
            "fresh_describe_commands_exact_identity_count_must_equal": 0,
            "fresh_describe_invocations_exact_identity_count_must_equal": 0,
            "fresh_exact_name_history_count_must_equal": 0,
            "history_all_pages_required": True,
            "local_o_excl_plan_nonce_required": True,
            "plan_nonce_emitted_by_renderer": False,
            "plan_nonce_must_be_retained_root_only": True,
            "predecessor_acceptance_digest_must_be_machine_verified": True,
            "provider_client_token_readback_supported": False,
            "provider_reads_performed_by_renderer": 0,
        },
        "request": request,
        "state": {
            "automatic_retry_allowed": False,
            "automatic_retry_count": 0,
            "dispatch_count_limit": 1,
            "initial": "HISTORY_ZERO_REQUIRED",
            "post_submit": "PROVIDER_READBACK_ONLY",
            "provider_unknown_recovery": (
                "READBACK_EXACT_NAME_COMMAND_INVOCATION_TARGET_NEVER_RESUBMIT"
            ),
            "provider_unknown_allowed_reads": [
                "DescribeCommands",
                "DescribeInvocations",
                "DescribeInvocationResults",
            ],
            "provider_unknown_readback_all_pages_required": True,
            "provider_unknown_resubmit_allowed": False,
            "same_request_resubmit_allowed": False,
            "serial_next_action": (
                ACTION_ORDER[ACTION_ORDER.index(action) + 1]
                if action != ACTION_ORDER[-1]
                else None
            ),
            "terminal_exit_code": dict(TERMINAL_TRANSITIONS[action]),
        },
    }


def _validate_static_contract() -> None:
    if (
        tuple(ACTIONS) != ACTION_ORDER
        or tuple(action.target for action in ACTIONS.values()) != INSTANCE_KEYS
        or len(ACTIONS) != 4
        or len({action.name for action in ACTIONS.values()}) != 4
        or len({action.host_mode for action in ACTIONS.values()}) != 4
        or len(set(INSTANCE_KEYS)) != 4
        or TASK_TAG != ("noteai-task", "item27-internal-smoke-v1")
        or EXECUTOR_PATH != "deploy/production/internal_zero_provider_smoke.py"
        or set(TERMINAL_TRANSITIONS) != set(ACTIONS)
        or tuple(PREDECESSOR_ACCEPTANCE_SOURCES) != ACTION_ORDER
    ):
        raise RuntimeError("invalid action table")
    for action in ACTIONS.values():
        if (
            COMMAND_NAME.fullmatch(action.name) is None
            or action.timeout != PROVIDER_TIMEOUT_SECONDS[action.host_mode]
            or action.target not in INSTANCE_KEYS
            or action.host_mode not in {"api-c", "api-f", "worker-c", "worker-f"}
        ):
            raise RuntimeError("invalid action row")


def cli() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        result = render_request(parse_canonical(raw))
        output = canonical(result)
    except RequestError as exc:
        sys.stderr.write("ITEM27_INTERNAL_SMOKE_REQUEST_FAILED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM27_INTERNAL_SMOKE_REQUEST_FAILED:internal\n")
        return 2
    sys.stdout.buffer.write(output)
    return 0


_validate_static_contract()


if __name__ == "__main__":
    raise SystemExit(cli())
