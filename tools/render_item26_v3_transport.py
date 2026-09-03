#!/usr/bin/env python3
"""Render and validate the Secret-free Item 26 v3 transport chain."""

from __future__ import annotations

import ast
import base64
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATHS = {
    "source": REPOSITORY_ROOT / ".codex" / "item26-source-manifest.template.sh",
    "executor": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3.template.sh"
    ),
    "controller": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3-controller.template.py"
    ),
    "wrapper": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3-wrapper.template.sh"
    ),
    "readback": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-readback-v3.template.sh"
    ),
}
SUMMARY_LAYER_NAMES = (
    "source",
    "driver",
    "transfer_gzip",
    "executor",
    "executor_gzip",
    "controller",
    "controller_gzip",
    "wrapper",
    "readback",
    "readback_validator",
    "readback_payload",
    "readback_payload_gzip",
    "readback_wrapper",
)
SUMMARY_COMMAND_NAMES = ("command_content", "readback_command_content")
SUMMARY_KEYS = frozenset(
    SUMMARY_LAYER_NAMES
    + SUMMARY_COMMAND_NAMES
    + ("production_provenance", "public_bindings")
)
PLACEHOLDER = re.compile(br"@@[A-Z][A-Z0-9_]*@@")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DRIVER_START = b"cat >\"$DRIVER_PATH\" <<'PY'\n"
DRIVER_END = b"PY\nchmod 0600 \"$DRIVER_PATH\""
MAX_TEMPLATE_BYTES = 262144
MAX_BOUND_LAYER_BYTES = 131072
MAX_COMMAND_CONTENT_BYTES = 18000
EXPECTED_ENVELOPE_BYTES = 894
EXPECTED_DRIVER_BYTES = 18084
EXPECTED_DRIVER_SHA256 = (
    "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e"
)
_TEMPLATE_IDENTITY_ROWS = (
    (
        "source",
        35352,
        "7e2bc2651a9dcd4ca546a03a9ada937c9133f21c725b5d1508f69eb6ebe9668e",
    ),
    (
        "executor",
        16961,
        "87d70818bcf695e843325e0a1a475549c2e661f65919c695b8651acc53aad0b4",
    ),
    (
        "controller",
        10039,
        "b89ee0fdcf3420694d7a45547664e3ef12bb810ad2285b9feaf09c175c096c07",
    ),
    (
        "wrapper",
        3276,
        "5fd926666ccabd678be44fde5c0b3e1bdf5555ae249899448ea6746dd457c021",
    ),
    (
        "readback",
        25827,
        "ef80ff4eb3a090959882ff0dff392a309c7cb691f128394fb9767c5f07eca8b1",
    ),
)
TEMPLATE_IDENTITIES = MappingProxyType(
    {
        name: MappingProxyType({"bytes": size, "sha256": digest})
        for name, size, digest in _TEMPLATE_IDENTITY_ROWS
    }
)
PRODUCTION_PROVENANCE = MappingProxyType(
    {
        "gzip_arguments": ("-9", "-n", "-c"),
        "gzip_implementation": "GNU",
        "platform": "linux",
        "templates": TEMPLATE_IDENTITIES,
    }
)

READBACK_VALIDATOR_SOURCE = b"""import json
import os
import signal
import subprocess


FULL_KEYS = frozenset("NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK,host,host_identity_exact,control_metadata_exact,control_value_read_count,transfer_exact,task_root_present,task_root_exact,task_inventory_state,driver_exact,task_docker_config_exact,final_root_present,final_root_exact,output_state,helper_stdout_bytes,helper_stdout_value_read_count,helper_error_code,task_container_query_ok,task_container_count,task_container_exact,established_5432_count,original_database_state,manifest_readback_allowed,same_invocation_replay_allowed,new_capture_allowed,cleanup_allowed,temporary_account_delete_allowed,pitr_stage_allowed,worker_stage_allowed,automatic_retry_allowed,api_environment_value_read_count,storage_environment_value_read_count,source_secret_value_read_count,ciphertext_value_read_count,manifest_value_read_count,database_connection_count,database_write_count,object_read_count,object_write_count,provider_control_plane_mutation_count,runtime_container_start_count".split(","))
FIXED_KEYS = frozenset("NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK,automatic_retry_allowed,cleanup_allowed,manifest_readback_allowed,new_capture_allowed,pitr_stage_allowed,same_invocation_replay_allowed,temporary_account_delete_allowed,worker_stage_allowed".split(","))
BOOL_KEYS = frozenset("host_identity_exact,control_metadata_exact,transfer_exact,task_root_present,task_root_exact,driver_exact,task_docker_config_exact,final_root_present,final_root_exact,task_container_query_ok,task_container_exact,manifest_readback_allowed,same_invocation_replay_allowed,new_capture_allowed,cleanup_allowed,temporary_account_delete_allowed,pitr_stage_allowed,worker_stage_allowed,automatic_retry_allowed".split(","))
ZERO_KEYS = frozenset("control_value_read_count,helper_stdout_value_read_count,api_environment_value_read_count,storage_environment_value_read_count,source_secret_value_read_count,ciphertext_value_read_count,manifest_value_read_count,database_connection_count,database_write_count,object_read_count,object_write_count,provider_control_plane_mutation_count,runtime_container_start_count".split(","))
INVENTORIES = frozenset({"ABSENT", "UNSAFE", "PRE_DOCKER_EXACT", "HELPER_EXACT", "POST_MOVE_EXACT"})
OUTPUTS = frozenset({"ABSENT", "UNSAFE", "EMPTY", "MANIFEST_PRESENT"})
FIXED_CODES = frozenset("metadata,race,read,env,dsn,identity,capability,envelope,key,write,output,payload,api_env,topology,storage,backend,session,owner,tables,rls,migrations,database,references,privacy,size,rollback".split(","))
PRE_CONNECT_CODES = frozenset("metadata,race,read,env,dsn,identity,capability,envelope,key,output,payload,api_env,topology,storage,backend".split(","))
DEFINITE_CONNECTED_CODES = frozenset("session,owner,tables,rls,write,database,references,privacy,size".split(","))
FIXED = {"NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK":"READBACK_UNKNOWN","automatic_retry_allowed":False,"cleanup_allowed":False,"manifest_readback_allowed":False,"new_capture_allowed":False,"pitr_stage_allowed":False,"same_invocation_replay_allowed":False,"temporary_account_delete_allowed":False,"worker_stage_allowed":False}


def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\\n").encode("ascii")


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def optional_int(value, maximum):
    return value is None or (type(value) is int and 0 <= value <= maximum)


def classify(value):
    identity_exact, control_exact, transfer_exact = (value[key] for key in ("host_identity_exact", "control_metadata_exact", "transfer_exact"))
    socket_count, container_ok, container_count = (value[key] for key in ("established_5432_count", "task_container_query_ok", "task_container_count"))
    task_present, task_exact, inventory, output = (value[key] for key in ("task_root_present", "task_root_exact", "task_inventory_state", "output_state"))
    final_present, final_exact, stdout_bytes, code = (value[key] for key in ("final_root_present", "final_root_exact", "helper_stdout_bytes", "helper_error_code"))
    status, database_state, allowed = "UNCLASSIFIED_UNKNOWN", "UNKNOWN", False
    if not identity_exact or not control_exact or socket_count is None:
        status = "IDENTITY_OR_CONTROL_UNKNOWN"
    elif socket_count != 0:
        status, database_state = "DATABASE_SOCKET_PRESENT_UNKNOWN", "CURRENT_CONNECTION_PRESENT_UNKNOWN"
    elif not container_ok or container_count is None:
        status = "CONTAINER_STATE_UNKNOWN"
    elif container_count > 0:
        status, database_state = "CONTAINER_PRESENT_UNKNOWN", "TASK_EXECUTION_OR_RESIDUE_UNKNOWN"
    elif final_present:
        path_exact = (not task_present and transfer_exact) or (task_exact and inventory == "POST_MOVE_EXACT" and value["driver_exact"])
        if final_exact and path_exact:
            status, database_state, allowed = "MANIFEST_COMMITTED_READBACK_REQUIRED", "CONNECTED_READ_ONLY_ROLLBACK", True
        else:
            status = "UNSAFE_FINAL_RESIDUE"
    elif not task_present:
        if transfer_exact:
            status, database_state = "NO_TASK_NO_FINAL_EXECUTION_UNPROVEN", "EXECUTION_UNPROVEN"
        else:
            status = "MISSING_OR_UNSAFE_INPUT"
    elif not task_exact:
        status = "UNSAFE_TASK_RESIDUE"
    elif inventory == "PRE_DOCKER_EXACT" and output == "EMPTY":
        status, database_state = "PRE_DOCKER_RESIDUE", "PRE_DATABASE_BARRIER"
    elif inventory == "HELPER_EXACT" and output == "MANIFEST_PRESENT":
        status, database_state, allowed = "STAGED_UNCOMMITTED_READBACK_REQUIRED", "CONNECTED_READ_ONLY_ROLLBACK", True
    elif inventory == "HELPER_EXACT" and output == "EMPTY" and stdout_bytes == 0 and code in PRE_CONNECT_CODES:
        status, database_state = "PRECONNECT_FIXED_RETAINED", "PRE_CONNECT"
    elif inventory == "HELPER_EXACT" and output == "EMPTY" and stdout_bytes == 0 and code in DEFINITE_CONNECTED_CODES:
        status, database_state = "POSTCONNECT_FIXED_NO_COMMIT", "CONNECTED_READ_ONLY_ROLLBACK_EXPECTED"
    elif inventory == "HELPER_EXACT" and output == "EMPTY" and stdout_bytes == 0 and code == "migrations":
        status, database_state = "MIGRATIONS_PHASE_NO_COMMIT_UNKNOWN", "MIGRATIONS_BARRIER_UNKNOWN"
    elif inventory == "HELPER_EXACT" and output == "EMPTY" and stdout_bytes == 0 and code == "rollback":
        status, database_state = "ROLLBACK_OUTCOME_UNKNOWN", "CONNECTED_ROLLBACK_UNKNOWN"
    elif inventory == "HELPER_EXACT" and output == "EMPTY" and stdout_bytes == 0:
        status, database_state = "DB_BARRIER_NO_COMMIT_UNKNOWN", "DB_BARRIER_UNKNOWN"
    return status, database_state, allowed


def validate_full(value):
    status = value.get("NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK")
    container_count = value.get("task_container_count")
    task_present = value.get("task_root_present")
    task_exact = value.get("task_root_exact")
    inventory = value.get("task_inventory_state")
    output = value.get("output_state")
    helper_bytes = value.get("helper_stdout_bytes")
    helper_code = value.get("helper_error_code")
    task_absent_exact = (
        not task_present
        and not task_exact
        and inventory == "ABSENT"
        and not value.get("driver_exact")
        and not value.get("task_docker_config_exact")
        and output == "ABSENT"
        and helper_bytes is None
        and helper_code is None
    )
    task_exact_shape = (
        task_present
        and task_exact
        and value.get("driver_exact")
        and value.get("task_docker_config_exact")
        and (
            (inventory == "PRE_DOCKER_EXACT" and output == "EMPTY" and helper_bytes is None and helper_code is None)
            or (inventory == "HELPER_EXACT" and output in {"EMPTY", "MANIFEST_PRESENT"} and type(helper_bytes) is int)
            or (inventory == "POST_MOVE_EXACT" and output == "ABSENT" and type(helper_bytes) is int and helper_code is None)
        )
    )
    task_unsafe_shape = task_present and not task_exact and inventory == "UNSAFE"
    if (
        set(value) != FULL_KEYS
        or type(status) is not str
        or value.get("host") != "API-C"
        or value.get("task_inventory_state") not in INVENTORIES
        or value.get("output_state") not in OUTPUTS
        or value.get("helper_error_code") not in FIXED_CODES | {None}
        or any(type(value.get(key)) is not bool for key in BOOL_KEYS)
        or any(type(value.get(key)) is not int or value[key] != 0 for key in ZERO_KEYS)
        or not optional_int(value.get("helper_stdout_bytes"), 4096)
        or not optional_int(container_count, 65536)
        or not optional_int(value.get("established_5432_count"), 65536)
        or not (task_absent_exact or task_exact_shape or task_unsafe_shape)
        or (helper_code is not None and not (task_exact and inventory == "HELPER_EXACT"))
        or (not value.get("final_root_present") and value.get("final_root_exact"))
        or value.get("manifest_readback_allowed") is not (status in {"MANIFEST_COMMITTED_READBACK_REQUIRED", "STAGED_UNCOMMITTED_READBACK_REQUIRED"})
        or any(value.get(key) is not False for key in ("same_invocation_replay_allowed", "new_capture_allowed", "cleanup_allowed", "temporary_account_delete_allowed", "pitr_stage_allowed", "worker_stage_allowed", "automatic_retry_allowed"))
        or (not value["task_container_query_ok"] and (container_count not in {None, 1} or value["task_container_exact"]))
        or (value["task_container_query_ok"] and container_count is None)
        or (value["task_container_query_ok"] and container_count == 0 and not value["task_container_exact"])
        or (value["task_container_query_ok"] and type(container_count) is int and container_count > 1 and value["task_container_exact"])
        or classify(value) != (status, value.get("original_database_state"), value.get("manifest_readback_allowed"))
    ):
        raise ValueError("full_schema")


def emit(value, code):
    body = canonical(value)
    if len(body) > 4096:
        os._exit(4)
    try:
        if os.write(1, body) != len(body):
            os._exit(4)
    except BaseException:
        os._exit(4)
    os._exit(code)


try:
    process = subprocess.Popen(
        ["/bin/bash", "-s"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},
        close_fds=True, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(READBACK_RAW, timeout=90)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except BaseException:
            pass
        try:
            process.communicate(timeout=5)
        except BaseException:
            pass
        raise
    if stderr or not stdout.endswith(b"\\n") or stdout.count(b"\\n") != 1 or len(stdout) > 4096 or process.returncode not in (0, 4):
        raise ValueError("terminal_shape")
    value = json.loads(stdout.decode("ascii"), object_pairs_hook=no_duplicates)
    if not isinstance(value, dict) or canonical(value) != stdout:
        raise ValueError("terminal_canonical")
    if process.returncode == 0:
        validate_full(value)
    elif set(value) != FIXED_KEYS or value != FIXED:
        raise ValueError("fixed_schema")
    emit(value, process.returncode)
except BaseException:
    emit(FIXED, 4)
"""


READBACK_WRAPPER_TEMPLATE = b"""#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET

exec python3 -I -B - <<'PY'
import base64, gzip, hashlib, os, re


GZIP_BYTES = @@READBACK_PAYLOAD_GZIP_BYTES@@
GZIP_SHA256 = "@@READBACK_PAYLOAD_GZIP_SHA256@@"
RAW_BYTES = @@READBACK_PAYLOAD_BYTES@@
RAW_SHA256 = "@@READBACK_PAYLOAD_SHA256@@"
GZIP_B85 = b"@@READBACK_PAYLOAD_GZIP_B85@@"
VALIDATOR_BYTES = @@READBACK_VALIDATOR_BYTES@@
VALIDATOR_SHA256 = "@@READBACK_VALIDATOR_SHA256@@"
READBACK_BYTES = @@READBACK_BYTES@@
READBACK_SHA256 = "@@READBACK_SHA256@@"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
B85 = re.compile(br"^[0-9A-Za-z!#$%&()*+\\-;<=>?@^_\\x60{|}~]+$")
FIXED = b'{"NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK":"READBACK_UNKNOWN","automatic_retry_allowed":false,"cleanup_allowed":false,"manifest_readback_allowed":false,"new_capture_allowed":false,"pitr_stage_allowed":false,"same_invocation_replay_allowed":false,"temporary_account_delete_allowed":false,"worker_stage_allowed":false}\\n'


def fixed():
    try:
        if os.write(1, FIXED) != len(FIXED):
            os._exit(4)
    except BaseException:
        os._exit(4)
    os._exit(4)


try:
    if type(GZIP_BYTES) is not int or type(RAW_BYTES) is not int or type(VALIDATOR_BYTES) is not int or type(READBACK_BYTES) is not int or not 1 <= GZIP_BYTES <= 131072 or RAW_BYTES != 8 + VALIDATOR_BYTES + READBACK_BYTES or not 1 <= VALIDATOR_BYTES <= 131072 or not 1 <= READBACK_BYTES <= 131072 or any(HEX64.fullmatch(value) is None for value in (GZIP_SHA256, RAW_SHA256, VALIDATOR_SHA256, READBACK_SHA256)) or B85.fullmatch(GZIP_B85) is None or len(GZIP_B85) != (GZIP_BYTES * 5 + 3) // 4:
        raise ValueError("binding")
    compressed = base64.b85decode(GZIP_B85)
    if len(compressed) != GZIP_BYTES or hashlib.sha256(compressed).hexdigest() != GZIP_SHA256:
        raise ValueError("gzip_hash")
    raw = gzip.decompress(compressed)
    if len(raw) != RAW_BYTES or hashlib.sha256(raw).hexdigest() != RAW_SHA256:
        raise ValueError("raw_hash")
    if not raw[:8].isdigit() or int(raw[:8]) != VALIDATOR_BYTES:
        raise ValueError("split")
    validator = raw[8:8 + VALIDATOR_BYTES]
    readback = raw[8 + VALIDATOR_BYTES:]
    if hashlib.sha256(validator).hexdigest() != VALIDATOR_SHA256 or hashlib.sha256(readback).hexdigest() != READBACK_SHA256:
        raise ValueError("component_hash")
    code = compile(validator.decode("ascii"), "<item26-v3-readback-validator>", "exec", dont_inherit=True)
    exec(code, {"__name__": "__main__", "READBACK_RAW": readback})
    raise RuntimeError("validator_returned")
except BaseException:
    fixed()
PY
"""


class RenderError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _production_provenance_summary() -> dict[str, object]:
    return {
        "gzip_arguments": list(PRODUCTION_PROVENANCE["gzip_arguments"]),
        "gzip_implementation": PRODUCTION_PROVENANCE["gzip_implementation"],
        "platform": PRODUCTION_PROVENANCE["platform"],
        "templates": {
            name: dict(identity)
            for name, identity in TEMPLATE_IDENTITIES.items()
        },
    }


def _read_template(name: str) -> bytes:
    path = TEMPLATE_PATHS[name]
    expected = TEMPLATE_IDENTITIES[name]
    try:
        before = path.lstat()
    except OSError as exc:
        raise RenderError("{}_template_stat".format(name)) from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size != expected["bytes"]
        or not 1 <= before.st_size <= MAX_TEMPLATE_BYTES
    ):
        raise RenderError("{}_template_metadata".format(name))
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        file_descriptor = os.open(str(path), flags)
        try:
            opened = os.fstat(file_descriptor)
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
            ):
                raise RenderError("{}_template_race".format(name))
            payload = b""
            while len(payload) <= expected["bytes"]:
                chunk = os.read(
                    file_descriptor,
                    min(65536, expected["bytes"] + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload += chunk
            closed = os.fstat(file_descriptor)
            if (
                closed.st_dev,
                closed.st_ino,
                closed.st_mode,
                closed.st_size,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
            ):
                raise RenderError("{}_template_race".format(name))
        finally:
            os.close(file_descriptor)
        after = path.lstat()
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError("{}_template_read".format(name)) from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise RenderError("{}_template_race".format(name))
    if len(payload) != expected["bytes"] or _sha256(payload) != expected["sha256"]:
        raise RenderError("{}_template_identity".format(name))
    _validate_ascii_lf(name + "_template", payload)
    return payload


def _validate_ascii_lf(name: str, payload: bytes) -> None:
    if not payload or b"\x00" in payload or b"\r" in payload:
        raise RenderError(name + "_encoding")
    try:
        payload.decode("ascii")
    except UnicodeError as exc:
        raise RenderError(name + "_encoding") from exc
    if not payload.endswith(b"\n"):
        raise RenderError(name + "_terminal_lf")


def _render(name: str, template: bytes, bindings: dict[bytes, bytes]) -> bytes:
    if not bindings:
        raise RenderError(name + "_bindings")
    expected = Counter({token: 1 for token in bindings})
    supplied = Counter(PLACEHOLDER.findall(template))
    if supplied != expected or template.count(b"@@") != 2 * len(bindings):
        raise RenderError(name + "_placeholder_inventory")
    for token, value in bindings.items():
        if (
            PLACEHOLDER.fullmatch(token) is None
            or not value
            or b"\n" in value
            or b"\r" in value
            or b"\x00" in value
        ):
            raise RenderError(name + "_binding_value")

    rendered = PLACEHOLDER.sub(lambda match: bindings[match.group(0)], template)
    # Base85 is opaque data and may naturally contain a bare ``@@`` pair.
    # Only a complete placeholder-shaped token represents unresolved syntax.
    if PLACEHOLDER.search(rendered) is not None:
        raise RenderError(name + "_placeholder_residue")
    _validate_ascii_lf(name, rendered)
    return rendered


def _run_bash_syntax(name: str, payload: bytes) -> None:
    try:
        result = subprocess.run(
            ["/bin/bash", "-n", "-s"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except BaseException as exc:
        raise RenderError(name + "_bash_syntax") from exc
    if result.returncode != 0 or result.stdout or len(result.stderr) > 4096:
        raise RenderError(name + "_bash_syntax")


def _python_heredocs(name: str, payload: bytes, expected_count: int) -> list[bytes]:
    lines = payload.splitlines(keepends=True)
    bodies = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if b"<<'PY'" not in line:
            index += 1
            continue
        body = []
        index += 1
        while index < len(lines) and lines[index] not in (b"PY\n", b"PY"):
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise RenderError(name + "_python_heredoc")
        bodies.append(b"".join(body))
        index += 1
    if len(bodies) != expected_count or any(not body for body in bodies):
        raise RenderError(name + "_python_heredoc")
    return bodies


def _python36_syntax(name: str, payload: bytes) -> None:
    try:
        source = payload.decode("ascii")
        ast.parse(source, filename=name, mode="exec", feature_version=(3, 6))
    except BaseException as exc:
        raise RenderError(name + "_python36_syntax") from exc


def _validate_bash_python(
    name: str,
    payload: bytes,
    expected_heredocs: int,
) -> None:
    _run_bash_syntax(name, payload)
    for index, body in enumerate(
        _python_heredocs(name, payload, expected_heredocs),
        start=1,
    ):
        _python36_syntax("{}_heredoc_{}".format(name, index), body)


def _extract_driver(source: bytes) -> bytes:
    if source.count(DRIVER_START) != 1 or source.count(DRIVER_END) != 1:
        raise RenderError("driver_markers")
    _head, separator, tail = source.partition(DRIVER_START)
    if not separator:
        raise RenderError("driver_markers")
    driver, separator, _remainder = tail.partition(DRIVER_END)
    if not separator or not driver.endswith(b"\n"):
        raise RenderError("driver_terminal_lf")
    if any(line.rstrip(b"\n") == b"PY" for line in driver.splitlines(keepends=True)):
        raise RenderError("driver_delimiter")
    _validate_ascii_lf("driver", driver)
    if len(driver) != EXPECTED_DRIVER_BYTES or _sha256(driver) != EXPECTED_DRIVER_SHA256:
        raise RenderError("driver_current_binding")

    probe = b"cat <<'PY'\n" + driver + b"PY\n"
    try:
        result = subprocess.run(
            ["/bin/bash", "-s"],
            input=probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except BaseException as exc:
        raise RenderError("driver_shell_roundtrip") from exc
    if result.returncode != 0 or result.stderr or result.stdout != driver:
        raise RenderError("driver_shell_roundtrip")
    return driver


def _production_gzip_compressor() -> Callable[[bytes], bytes]:
    if not sys.platform.startswith("linux"):
        raise RenderError("linux_required")
    clean_environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    try:
        version = subprocess.run(
            ["/usr/bin/gzip", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_environment,
            timeout=10,
            check=False,
        )
    except BaseException as exc:
        raise RenderError("gnu_gzip_required") from exc
    if (
        version.returncode != 0
        or version.stderr
        or len(version.stdout) > 8192
        or not version.stdout.startswith(b"gzip ")
        or b"Free Software Foundation" not in version.stdout
    ):
        raise RenderError("gnu_gzip_required")

    def compress(payload: bytes) -> bytes:
        try:
            result = subprocess.run(
                ["/usr/bin/gzip", "-9", "-n", "-c"],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_environment,
                timeout=30,
                check=False,
            )
        except BaseException as exc:
            raise RenderError("gnu_gzip") from exc
        if result.returncode != 0 or result.stderr:
            raise RenderError("gnu_gzip")
        return result.stdout

    return compress


def _compress(
    name: str,
    payload: bytes,
    compressor: Callable[[bytes], bytes],
) -> bytes:
    try:
        compressed = compressor(payload)
    except RenderError:
        raise
    except BaseException as exc:
        raise RenderError(name + "_gzip") from exc
    if (
        type(compressed) is not bytes
        or not 1 <= len(compressed) <= MAX_BOUND_LAYER_BYTES
    ):
        raise RenderError(name + "_gzip")
    try:
        restored = gzip.decompress(compressed)
    except BaseException as exc:
        raise RenderError(name + "_gzip_roundtrip") from exc
    if restored != payload:
        raise RenderError(name + "_gzip_roundtrip")
    return compressed


def _b85(name: str, payload: bytes) -> bytes:
    encoded = base64.b85encode(payload)
    try:
        restored = base64.b85decode(encoded)
    except BaseException as exc:
        raise RenderError(name + "_b85_roundtrip") from exc
    if restored != payload or b"\n" in encoded or b"\r" in encoded:
        raise RenderError(name + "_b85_roundtrip")
    return encoded


def _layer(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": _sha256(payload)}


def _command_content(name: str, payload: bytes) -> dict[str, object]:
    encoded = base64.b64encode(payload)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except BaseException as exc:
        raise RenderError(name + "_roundtrip") from exc
    if (
        decoded != payload
        or b"\n" in encoded
        or len(encoded) > MAX_COMMAND_CONTENT_BYTES
    ):
        raise RenderError(name + "_limit")
    return {
        "base64": encoded.decode("ascii"),
        "bytes": len(encoded),
        "sha256": _sha256(encoded),
    }


def _render_readback_transport(
    readback: bytes,
    gzip_compressor: Callable[[bytes], bytes],
) -> tuple[bytes, bytes, bytes, bytes, dict[str, object]]:
    readback_validator = READBACK_VALIDATOR_SOURCE
    _validate_ascii_lf("readback_validator", readback_validator)
    _python36_syntax("readback_validator", readback_validator)
    readback_payload = (
        "{:08d}".format(len(readback_validator)).encode("ascii")
        + readback_validator
        + readback
    )
    readback_payload_gzip = _compress(
        "readback_payload",
        readback_payload,
        gzip_compressor,
    )
    readback_wrapper = _render(
        "readback_wrapper",
        READBACK_WRAPPER_TEMPLATE,
        {
            b"@@READBACK_PAYLOAD_GZIP_BYTES@@": str(
                len(readback_payload_gzip)
            ).encode("ascii"),
            b"@@READBACK_PAYLOAD_GZIP_SHA256@@": _sha256(
                readback_payload_gzip
            ).encode("ascii"),
            b"@@READBACK_PAYLOAD_BYTES@@": str(
                len(readback_payload)
            ).encode("ascii"),
            b"@@READBACK_PAYLOAD_SHA256@@": _sha256(
                readback_payload
            ).encode("ascii"),
            b"@@READBACK_PAYLOAD_GZIP_B85@@": _b85(
                "readback_payload",
                readback_payload_gzip,
            ),
            b"@@READBACK_VALIDATOR_BYTES@@": str(
                len(readback_validator)
            ).encode("ascii"),
            b"@@READBACK_VALIDATOR_SHA256@@": _sha256(
                readback_validator
            ).encode("ascii"),
            b"@@READBACK_BYTES@@": str(len(readback)).encode("ascii"),
            b"@@READBACK_SHA256@@": _sha256(readback).encode("ascii"),
        },
    )
    _validate_bash_python("readback_wrapper", readback_wrapper, 1)
    command = _command_content("readback_command_content", readback_wrapper)
    return (
        readback_validator,
        readback_payload,
        readback_payload_gzip,
        readback_wrapper,
        command,
    )


def _validate_public_inputs(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
) -> None:
    if type(envelope_bytes) is not int or envelope_bytes != EXPECTED_ENVELOPE_BYTES:
        raise RenderError("envelope_bytes")
    if (
        type(envelope_sha256) is not str
        or HEX64.fullmatch(envelope_sha256) is None
        or type(public_key_sha256) is not str
        or HEX64.fullmatch(public_key_sha256) is None
    ):
        raise RenderError("public_sha256")


def _render_item26_v3_transport_core(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    """Render artifacts for production or explicitly non-production tests."""

    _validate_public_inputs(envelope_bytes, envelope_sha256, public_key_sha256)
    templates = {name: _read_template(name) for name in TEMPLATE_PATHS}

    source = _render(
        "source",
        templates["source"],
        {
            b"@@ENVELOPE_BYTES@@": str(envelope_bytes).encode("ascii"),
            b"@@ENVELOPE_SHA256@@": envelope_sha256.encode("ascii"),
            b"@@PUBLIC_KEY_SHA256@@": public_key_sha256.encode("ascii"),
        },
    )
    _validate_bash_python("source", source, 3)
    driver = _extract_driver(source)
    transfer_gzip = _compress("transfer", source, gzip_compressor)
    if len(source) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("source_size")

    executor = _render(
        "executor",
        templates["executor"],
        {
            b"@@TRANSFER_BYTES@@": str(len(transfer_gzip)).encode("ascii"),
            b"@@TRANSFER_SHA256@@": _sha256(transfer_gzip).encode("ascii"),
            b"@@RAW_BYTES@@": str(len(source)).encode("ascii"),
            b"@@RAW_SHA256@@": _sha256(source).encode("ascii"),
        },
    )
    _validate_bash_python("executor", executor, 1)
    executor_gzip = _compress("executor", executor, gzip_compressor)
    if len(executor) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("executor_size")

    executor_b85 = _b85("executor", executor_gzip)
    controller = _render(
        "controller",
        templates["controller"],
        {
            b"@@EXECUTOR_GZIP_BYTES@@": str(len(executor_gzip)).encode("ascii"),
            b"@@EXECUTOR_GZIP_SHA256@@": _sha256(executor_gzip).encode("ascii"),
            b"@@EXECUTOR_BYTES@@": str(len(executor)).encode("ascii"),
            b"@@EXECUTOR_SHA256@@": _sha256(executor).encode("ascii"),
            b"@@EXECUTOR_GZIP_B85@@": executor_b85,
        },
    )
    _python36_syntax("controller", controller)
    controller_gzip = _compress("controller", controller, gzip_compressor)
    if len(controller) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("controller_size")

    controller_b85 = _b85("controller", controller_gzip)
    wrapper = _render(
        "wrapper",
        templates["wrapper"],
        {
            b"@@CONTROLLER_GZIP_BYTES@@": str(len(controller_gzip)).encode("ascii"),
            b"@@CONTROLLER_GZIP_SHA256@@": _sha256(controller_gzip).encode("ascii"),
            b"@@CONTROLLER_BYTES@@": str(len(controller)).encode("ascii"),
            b"@@CONTROLLER_SHA256@@": _sha256(controller).encode("ascii"),
            b"@@CONTROLLER_GZIP_B85@@": controller_b85,
        },
    )
    _validate_bash_python("wrapper", wrapper, 1)

    readback = _render(
        "readback",
        templates["readback"],
        {
            b"@@TRANSFER_BYTES@@": str(len(transfer_gzip)).encode("ascii"),
            b"@@TRANSFER_SHA256@@": _sha256(transfer_gzip).encode("ascii"),
            b"@@DRIVER_BYTES@@": str(len(driver)).encode("ascii"),
            b"@@DRIVER_SHA256@@": _sha256(driver).encode("ascii"),
        },
    )
    _validate_bash_python("readback", readback, 1)
    (
        readback_validator,
        readback_payload,
        readback_payload_gzip,
        readback_wrapper,
        readback_command_content,
    ) = _render_readback_transport(readback, gzip_compressor)

    command_content = _command_content("command_content", wrapper)

    artifacts = {
        "source": source,
        "driver": driver,
        "transfer_gzip": transfer_gzip,
        "executor": executor,
        "executor_gzip": executor_gzip,
        "controller": controller,
        "controller_gzip": controller_gzip,
        "wrapper": wrapper,
        "readback": readback,
        "readback_validator": readback_validator,
        "readback_payload": readback_payload,
        "readback_payload_gzip": readback_payload_gzip,
        "readback_wrapper": readback_wrapper,
    }
    if set(artifacts) != set(SUMMARY_LAYER_NAMES):
        raise RenderError("artifact_contract")
    sizing = {name: _layer(artifacts[name]) for name in SUMMARY_LAYER_NAMES}
    sizing["command_content"] = command_content
    sizing["readback_command_content"] = readback_command_content
    return {"artifacts": artifacts, "sizing": sizing}


def _render_item26_v3_transport_for_test(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    """Return a result that cannot be mistaken for a production receipt."""

    result = _render_item26_v3_transport_core(
        envelope_bytes,
        envelope_sha256,
        public_key_sha256,
        gzip_compressor=gzip_compressor,
    )
    return {
        "artifacts": result["artifacts"],
        "mode": "TEST_SIZING_ONLY",
        "sizing": result["sizing"],
    }


def render_item26_v3_transport(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
) -> dict[str, object]:
    """Render the authoritative Linux/GNU transport and production summary."""

    _validate_public_inputs(envelope_bytes, envelope_sha256, public_key_sha256)
    result = _render_item26_v3_transport_core(
        envelope_bytes,
        envelope_sha256,
        public_key_sha256,
        gzip_compressor=_production_gzip_compressor(),
    )
    summary = dict(result["sizing"])
    summary["production_provenance"] = _production_provenance_summary()
    summary["public_bindings"] = {
        "envelope_bytes": envelope_bytes,
        "envelope_sha256": envelope_sha256,
        "public_key_sha256": public_key_sha256,
    }
    canonical_summary(summary)
    return {"artifacts": result["artifacts"], "summary": summary}


def canonical_summary(summary: dict[str, object]) -> bytes:
    if set(summary) != SUMMARY_KEYS:
        raise RenderError("summary_contract")
    for name in SUMMARY_LAYER_NAMES:
        value = summary.get(name)
        if (
            type(value) is not dict
            or set(value) != {"bytes", "sha256"}
            or type(value.get("bytes")) is not int
            or value["bytes"] < 1
            or type(value.get("sha256")) is not str
            or HEX64.fullmatch(value["sha256"]) is None
        ):
            raise RenderError("summary_contract")
    command_targets = {
        "command_content": "wrapper",
        "readback_command_content": "readback_wrapper",
    }
    for command_name, target_name in command_targets.items():
        command = summary.get(command_name)
        if (
            type(command) is not dict
            or set(command) != {"base64", "bytes", "sha256"}
            or type(command.get("base64")) is not str
            or type(command.get("bytes")) is not int
            or not 1 <= command["bytes"] <= MAX_COMMAND_CONTENT_BYTES
            or len(command["base64"].encode("ascii")) != command["bytes"]
            or type(command.get("sha256")) is not str
            or HEX64.fullmatch(command["sha256"]) is None
        ):
            raise RenderError("summary_contract")
        try:
            command_bytes = command["base64"].encode("ascii")
            decoded_command = base64.b64decode(command_bytes, validate=True)
        except BaseException as exc:
            raise RenderError("summary_contract") from exc
        if (
            _sha256(command_bytes) != command["sha256"]
            or len(decoded_command) != summary[target_name]["bytes"]
            or _sha256(decoded_command) != summary[target_name]["sha256"]
        ):
            raise RenderError("summary_contract")
    public_bindings = summary.get("public_bindings")
    if (
        type(public_bindings) is not dict
        or set(public_bindings)
        != {"envelope_bytes", "envelope_sha256", "public_key_sha256"}
    ):
        raise RenderError("summary_contract")
    _validate_public_inputs(
        public_bindings.get("envelope_bytes"),
        public_bindings.get("envelope_sha256"),
        public_bindings.get("public_key_sha256"),
    )
    if summary.get("production_provenance") != _production_provenance_summary():
        raise RenderError("summary_contract")
    body = (
        json.dumps(
            summary,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    decoded = json.loads(body.decode("ascii"))
    if decoded != summary:
        raise RenderError("summary_canonical")
    return body


def _write_all(file_descriptor: int, payload: bytes) -> bool:
    offset = 0
    try:
        while offset < len(payload):
            written = os.write(file_descriptor, payload[offset:])
            if written <= 0:
                return False
            offset += written
    except BaseException:
        return False
    return True


def _cli(argv: list[str]) -> int:
    try:
        if len(argv) != 3 or re.fullmatch(r"[1-9][0-9]{0,5}", argv[0]) is None:
            raise RenderError("arguments")
        rendered = render_item26_v3_transport(
            int(argv[0]),
            argv[1],
            argv[2],
        )
        body = canonical_summary(rendered["summary"])
    except RenderError as exc:
        error = "ITEM26_V3_RENDER_FAILED:{}\n".format(exc.code).encode("ascii")
        _write_all(2, error)
        return 2
    except BaseException:
        _write_all(2, b"ITEM26_V3_RENDER_FAILED:internal\n")
        return 2
    return 0 if _write_all(1, body) else 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
