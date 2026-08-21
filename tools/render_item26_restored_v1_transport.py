#!/usr/bin/env python3
"""Render the Secret-free, write-once Item 26 restored-capture v1 chain."""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import MappingProxyType
from typing import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
from tools import render_item26_v3_transport as v3


TEMPLATE_PATHS = MappingProxyType(
    {
        "capture": (
            REPOSITORY_ROOT
            / ".codex"
            / "item26-restored-capture-v1.template.sh"
        ),
        "executor": (
            REPOSITORY_ROOT
            / ".codex"
            / "item26-restored-capture-executor-v1.template.sh"
        ),
    }
)
TEMPLATE_IDENTITIES = MappingProxyType(
    {
        "capture": MappingProxyType(
            {
                "bytes": 46846,
                "sha256": (
                    "906a06fd919fc0e90c735f79b13d3bb5bac645c4c19a9dda2053dd2946601c1e"
                ),
            }
        ),
        "executor": MappingProxyType(
            {
                "bytes": 13365,
                "sha256": (
                    "a8bc036e11d6e7a5d3a9fafdc307f9ac5470b026db93bca9ca2c686dfb1bc9e6"
                ),
            }
        ),
    }
)
SOURCE_PLACEHOLDER_COUNTS = MappingProxyType(
    {
        b"@@BUILDER_IDENTITY_SHA256@@": 2,
        b"@@CONTROL_ENVELOPE_BYTES@@": 2,
        b"@@CONTROL_ENVELOPE_SHA256@@": 2,
        b"@@RECIPIENT_PUBLIC_KEY_SHA256@@": 2,
        b"@@SOURCE_MANIFEST_BYTES@@": 1,
        b"@@SOURCE_MANIFEST_FILE_SHA256@@": 1,
        b"@@SOURCE_MANIFEST_SHA256@@": 1,
        b"@@RESTORED_TOPOLOGY_SHA256@@": 1,
        b"@@STORAGE_CONFIG_SHA256@@": 1,
    }
)
TRANSFER_PATH = "/var/lib/noteai/item26-restored-v1/restored-capture-transfer-v1.sh.gz"
CONTROL_ROOT = "/var/lib/noteai/item26-restored-v1/control"
CONTROL_ENVELOPE_PATH = CONTROL_ROOT + "/control-envelope.json"
MAX_TEMPLATE_BYTES = 131072
MAX_CONTROL_ENVELOPE_BYTES = 12288
MAX_SOURCE_MANIFEST_BYTES = 1048576
MAX_COMMAND_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(br"@@[A-Z][A-Z0-9_]*@@")
SUMMARY_LAYER_NAMES = (
    "capture",
    "capture_gzip",
    "control_envelope",
    "executor",
    "executor_gzip",
    "capture_wrapper",
)
SUMMARY_COMMAND_NAMES = ("capture_command_content",)
SUMMARY_KEYS = frozenset(
    SUMMARY_LAYER_NAMES
    + SUMMARY_COMMAND_NAMES
    + ("production_provenance", "public_bindings")
)


CAPTURE_WRAPPER_TEMPLATE = b"""#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
exec python3 -I -B - <<'PY'
import base64,gzip,hashlib,json,os,re,signal,subprocess
GZIP_BYTES=@@GZIP_BYTES@@
GZIP_SHA256="@@GZIP_SHA256@@"
RAW_BYTES=@@RAW_BYTES@@
RAW_SHA256="@@RAW_SHA256@@"
GZIP_B85=b"@@GZIP_B85@@"
started=False
H=re.compile(r"^[0-9a-f]{64}$")
PRE=frozenset("NOTEAI_ITEM26_RESTORED_CAPTURE automatic_retry_allowed database_attempted_state incident_class new_capture_allowed phase same_invocation_replay_allowed".split())
U=PRE|{"readback_required"}; E=U|{"transfer_state"}
P=frozenset("absolute_tool container_cleanup control_inventory control_root db_socket_after db_socket_before docker_service docker_version driver_contract driver_preconnect_failure driver_stderr driver_stdout driver_terminal envelope envelope_hash final_fsync final_hash final_inventory final_manifest final_move final_preexisting final_receipt final_receipt_hash final_root identity image key_pair loader output_inventory persistent_parent persistent_root preconnect_contract preconnect_retention preconnect_stderr preconnect_stdout preexisting_capture_state preflight private_hash private_key public_hash public_key receipt replay_barrier restored_read_only_capture root task_container task_identity task_retention terminal_promotion tool".split())
EP=frozenset("capture_contract capture_failure_stream capture_json capture_output_limit capture_pass_stream capture_returncode capture_shape capture_spawn capture_timeout executor_exception executor_preflight raw_hash transfer_after_capture transfer_hash transfer_metadata".split())
M=frozenset("release_commit database_engine database_schema database_migrations database_tables database_references private_objects".split())
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n").encode("ascii")
def fixed():
    value={"NOTEAI_ITEM26_RESTORED_CAPTURE":"UNKNOWN" if started else "FAIL","automatic_retry_allowed":False,"database_attempted_state":"UNKNOWN" if started else "NO","incident_class":"CONNECTED_UNKNOWN" if started else "PRE_CONNECT","new_capture_allowed":False,"phase":"loader","same_invocation_replay_allowed":False}
    if started: value["readback_required"]=True
    return value
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate")
        result[key]=value
    return result
def valid(value,rc):
    if type(value) is not dict: return False
    keys=set(value)
    if len(value)==46:
        passed=rc==0
        if rc not in (0,3) or value["NOTEAI_ITEM26_RESTORED_CAPTURE"]!=("PASS" if passed else "FAIL") or value["incident_class"]!=("CONNECTED_KNOWN_READ_ONLY" if passed else "CONNECTED_KNOWN_READ_ONLY_MISMATCH") or value["verified"] is not passed or value["comparison_exact"] is not passed: return False
        bools={"attempt_sentinel_retained":True,"automatic_retry_allowed":False,"control_material_retained":True,"new_capture_allowed":False,"owner_table_contract_exact":True,"readback_required":False,"reconciliation_retained":True,"restored_manifest_retained":True,"rls_contract_exact":True,"row_security_off":True,"same_invocation_replay_allowed":False,"search_path_exact":True,"task_root_retained":True,"transfer_retained":True}
        ints={"container_residue_count":0,"database_connection_count":1,"database_transaction_count":1,"database_write_count":0,"force_rls_table_count":0,"managed_owner_activation_count":1,"object_contents_read":0,"object_keys_emitted":0,"object_write_count":0,"oss_get_request_count":0,"owner_mismatch_count":0,"persistent_permission_mutation_count":0,"postgresql_major_version":16,"rls_table_count":19,"row_values_emitted":0,"runtime_container_start_count":1,"secret_values_emitted":0,"table_count":56}
        if any(value[k] is not x for k,x in bools.items()) or any(type(value[k]) is not int or value[k]!=x for k,x in ints.items()) or type(value["manifest_bytes"]) is not int or value["manifest_bytes"]<1 or type(value["oss_list_request_count"]) is not int or value["oss_list_request_count"]<1 or type(value["oss_head_request_count"]) is not int or value["oss_head_request_count"]<0: return False
        if value["transaction_terminal"]!="ROLLBACK" or value["oss_operation_mode"]!="LIST_HEAD_ONLY" or value["reconciliation_schema_version"]!="noteai.item26.restored-reconciliation.v1" or any(type(value[k]) is not str or H.fullmatch(value[k]) is None for k in ("restored_manifest_file_sha256","restored_manifest_sha256","source_manifest_sha256")): return False
        codes=value["mismatch_codes"]
        return type(codes) is list and all(type(x) is str for x in codes) and len(codes)==len(set(codes)) and not set(codes)-M and (codes==[] if passed else bool(codes))
    if keys==PRE:
        return rc==3 and value["NOTEAI_ITEM26_RESTORED_CAPTURE"]=="FAIL" and value["automatic_retry_allowed"] is False and value["database_attempted_state"]=="NO" and value["incident_class"]=="PRE_CONNECT" and value["new_capture_allowed"] is False and value["same_invocation_replay_allowed"] is False and type(value["phase"]) is str and value["phase"] in P
    if keys==U:
        return rc==4 and value["NOTEAI_ITEM26_RESTORED_CAPTURE"]=="UNKNOWN" and value["automatic_retry_allowed"] is False and value["database_attempted_state"]=="UNKNOWN" and value["incident_class"]=="CONNECTED_UNKNOWN" and value["new_capture_allowed"] is False and value["readback_required"] is True and value["same_invocation_replay_allowed"] is False and type(value["phase"]) is str and value["phase"] in P
    if keys==E:
        return rc in (3,4) and value["NOTEAI_ITEM26_RESTORED_CAPTURE"]==("FAIL" if rc==3 else "UNKNOWN") and value["automatic_retry_allowed"] is False and value["database_attempted_state"]==("NO" if rc==3 else "UNKNOWN") and value["incident_class"]==("PRE_CONNECT" if rc==3 else "CONNECTED_UNKNOWN") and value["new_capture_allowed"] is False and value["readback_required"] is (rc==4) and value["same_invocation_replay_allowed"] is False and type(value["phase"]) is str and value["phase"] in EP and value["transfer_state"] in ({"UNVERIFIED","EXACT_RETAINED"} if rc==3 else {"UNKNOWN"})
    return False
try:
    if os.geteuid()!=0 or os.getegid()!=0 or type(GZIP_BYTES) is not int or type(RAW_BYTES) is not int or not 1<=GZIP_BYTES<=131072 or not 1<=RAW_BYTES<=131072 or re.fullmatch(r"[0-9a-f]{64}",GZIP_SHA256) is None or re.fullmatch(r"[0-9a-f]{64}",RAW_SHA256) is None: raise ValueError("binding")
    compressed=base64.b85decode(GZIP_B85)
    if len(compressed)!=GZIP_BYTES or hashlib.sha256(compressed).hexdigest()!=GZIP_SHA256: raise ValueError("gzip_hash")
    raw=gzip.decompress(compressed)
    if len(raw)!=RAW_BYTES or hashlib.sha256(raw).hexdigest()!=RAW_SHA256: raise ValueError("raw_hash")
    process=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},close_fds=True,start_new_session=True); started=True
    try: stdout,stderr=process.communicate(raw,timeout=1400)
    except BaseException:
        try: os.killpg(process.pid,signal.SIGKILL)
        except BaseException: pass
        try: process.communicate(timeout=10)
        except BaseException: pass
        raise
    if len(stdout)+len(stderr)>4096 or process.returncode not in (0,3,4): raise ValueError("terminal")
    body=stdout if process.returncode==0 else stderr
    if (process.returncode==0 and stderr) or (process.returncode!=0 and stdout) or not body.endswith(b"\\n") or body.count(b"\\n")!=1: raise ValueError("stream")
    value=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
    if canonical(value)!=body or not valid(value,process.returncode): raise ValueError("contract")
    descriptor=1 if process.returncode==0 else 2
    if os.write(descriptor,body)!=len(body): os._exit(4)
    os._exit(process.returncode)
except BaseException:
    body=canonical(fixed())
    try:
        if os.write(2,body)!=len(body): os._exit(4)
    except BaseException: os._exit(4)
    os._exit(4 if started else 3)
PY
"""


class RenderError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_hash(value: object, label: str) -> str:
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise RenderError(label)
    return value


def _read_template(name: str) -> bytes:
    path = TEMPLATE_PATHS[name]
    expected = TEMPLATE_IDENTITIES[name]
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_size != expected["bytes"]
            or not 1 <= before.st_size <= MAX_TEMPLATE_BYTES
        ):
            raise RenderError(name + "_template_metadata")
        descriptor = os.open(
            str(path),
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            body = b""
            while len(body) <= expected["bytes"]:
                chunk = os.read(
                    descriptor,
                    min(65536, expected["bytes"] + 1 - len(body)),
                )
                if not chunk:
                    break
                body += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError(name + "_template_read") from exc
    stable = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_size,
        row.st_mtime_ns,
    )
    if (
        stable(before) != stable(after)
        or (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size)
        != (before.st_dev, before.st_ino, before.st_mode, before.st_size)
        or (closed.st_dev, closed.st_ino, closed.st_mode, closed.st_size)
        != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size)
    ):
        raise RenderError(name + "_template_race")
    if len(body) != expected["bytes"] or _sha256(body) != expected["sha256"]:
        raise RenderError(name + "_template_identity")
    try:
        v3._validate_ascii_lf(name + "_template", body)
    except v3.RenderError as exc:
        raise RenderError(name + "_template_encoding") from exc
    return body


def _render_repeated(
    name: str,
    template: bytes,
    bindings: dict[bytes, bytes],
    expected_counts: dict[bytes, int],
) -> bytes:
    if Counter(PLACEHOLDER.findall(template)) != Counter(expected_counts):
        raise RenderError(name + "_placeholder_inventory")
    if set(bindings) != set(expected_counts):
        raise RenderError(name + "_bindings")
    for token, value in bindings.items():
        if (
            PLACEHOLDER.fullmatch(token) is None
            or not value
            or b"\n" in value
            or b"\r" in value
            or b"\x00" in value
        ):
            raise RenderError(name + "_binding_value")
    result = template
    for token, value in bindings.items():
        result = result.replace(token, value)
    if PLACEHOLDER.search(result) is not None:
        raise RenderError(name + "_placeholder_residue")
    try:
        v3._validate_ascii_lf(name, result)
    except v3.RenderError as exc:
        raise RenderError(name + "_encoding") from exc
    return result


def _render_once(
    name: str,
    template: bytes,
    bindings: dict[bytes, bytes],
) -> bytes:
    try:
        return v3._render(name, template, bindings)
    except v3.RenderError as exc:
        raise RenderError(name + "_render") from exc


def _compress(
    name: str,
    payload: bytes,
    compressor: Callable[[bytes], bytes],
) -> bytes:
    try:
        return v3._compress(name, payload, compressor)
    except v3.RenderError as exc:
        raise RenderError(name + "_gzip") from exc


def _b85(name: str, payload: bytes) -> bytes:
    try:
        return v3._b85(name, payload)
    except v3.RenderError as exc:
        raise RenderError(name + "_b85") from exc


def _validate_shell(name: str, payload: bytes, heredocs: int) -> None:
    try:
        v3._validate_bash_python(name, payload, heredocs)
    except v3.RenderError as exc:
        raise RenderError(name + "_syntax") from exc


def _command(name: str, payload: bytes) -> dict[str, object]:
    try:
        value = v3._command_content(name, payload)
    except v3.RenderError as exc:
        raise RenderError(name + "_limit") from exc
    if value["bytes"] > MAX_COMMAND_CONTENT_BYTES:
        raise RenderError(name + "_limit")
    return value


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RenderError("control_envelope_duplicate")
        result[key] = value
    return result


def _validate_control_envelope(value: bytes) -> dict[str, object]:
    if type(value) is not bytes or not 1 <= len(value) <= MAX_CONTROL_ENVELOPE_BYTES:
        raise RenderError("control_envelope_size")
    if b"\x00" in value or b"\r" in value or b"\n" in value:
        raise RenderError("control_envelope_encoding")
    try:
        envelope = json.loads(
            value.decode("ascii"),
            object_pairs_hook=_no_duplicates,
        )
        canonical = json.dumps(
            envelope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except RenderError:
        raise
    except BaseException as exc:
        raise RenderError("control_envelope_json") from exc
    if (
        canonical != value
        or type(envelope) is not dict
        or set(envelope)
        != {"schema_version", "algorithm", "wrapped_key", "nonce", "ciphertext"}
        or envelope.get("schema_version") != 1
        or envelope.get("algorithm") != "RSA-OAEP-SHA256+AES-256-GCM"
    ):
        raise RenderError("control_envelope_contract")
    try:
        wrapped = base64.b64decode(envelope["wrapped_key"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    except BaseException as exc:
        raise RenderError("control_envelope_base64") from exc
    if len(wrapped) != 384 or len(nonce) != 12 or len(ciphertext) < 16:
        raise RenderError("control_envelope_shape")
    return envelope


def _validate_public_inputs(
    control_envelope: bytes,
    recipient_public_key_sha256: str,
    builder_identity_sha256: str,
    source_manifest_bytes: int,
    source_manifest_file_sha256: str,
    source_manifest_sha256: str,
    restored_topology_sha256: str,
    storage_config_sha256: str,
) -> None:
    _validate_control_envelope(control_envelope)
    for label, value in (
        ("recipient_public_key_sha256", recipient_public_key_sha256),
        ("builder_identity_sha256", builder_identity_sha256),
        ("source_manifest_file_sha256", source_manifest_file_sha256),
        ("source_manifest_sha256", source_manifest_sha256),
        ("restored_topology_sha256", restored_topology_sha256),
        ("storage_config_sha256", storage_config_sha256),
    ):
        _validate_hash(value, label)
    if (
        type(source_manifest_bytes) is not int
        or not 1 <= source_manifest_bytes <= MAX_SOURCE_MANIFEST_BYTES
    ):
        raise RenderError("source_manifest_bytes")


def _layer(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": _sha256(payload)}


def _render_core(
    control_envelope: bytes,
    recipient_public_key_sha256: str,
    builder_identity_sha256: str,
    source_manifest_bytes: int,
    source_manifest_file_sha256: str,
    source_manifest_sha256: str,
    restored_topology_sha256: str,
    storage_config_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    _validate_public_inputs(
        control_envelope,
        recipient_public_key_sha256,
        builder_identity_sha256,
        source_manifest_bytes,
        source_manifest_file_sha256,
        source_manifest_sha256,
        restored_topology_sha256,
        storage_config_sha256,
    )
    capture_template = _read_template("capture")
    executor_template = _read_template("executor")
    envelope_sha256 = _sha256(control_envelope)
    capture = _render_repeated(
        "capture",
        capture_template,
        {
            b"@@BUILDER_IDENTITY_SHA256@@": builder_identity_sha256.encode("ascii"),
            b"@@CONTROL_ENVELOPE_BYTES@@": str(len(control_envelope)).encode("ascii"),
            b"@@CONTROL_ENVELOPE_SHA256@@": envelope_sha256.encode("ascii"),
            b"@@RECIPIENT_PUBLIC_KEY_SHA256@@": recipient_public_key_sha256.encode("ascii"),
            b"@@SOURCE_MANIFEST_BYTES@@": str(source_manifest_bytes).encode("ascii"),
            b"@@SOURCE_MANIFEST_FILE_SHA256@@": source_manifest_file_sha256.encode("ascii"),
            b"@@SOURCE_MANIFEST_SHA256@@": source_manifest_sha256.encode("ascii"),
            b"@@RESTORED_TOPOLOGY_SHA256@@": restored_topology_sha256.encode("ascii"),
            b"@@STORAGE_CONFIG_SHA256@@": storage_config_sha256.encode("ascii"),
        },
        dict(SOURCE_PLACEHOLDER_COUNTS),
    )
    _validate_shell("capture", capture, 7)
    capture_gzip = _compress("capture", capture, gzip_compressor)
    executor = _render_once(
        "executor",
        executor_template,
        {
            b"@@TRANSFER_BYTES@@": str(len(capture_gzip)).encode("ascii"),
            b"@@TRANSFER_SHA256@@": _sha256(capture_gzip).encode("ascii"),
            b"@@RAW_BYTES@@": str(len(capture)).encode("ascii"),
            b"@@RAW_SHA256@@": _sha256(capture).encode("ascii"),
        },
    )
    _validate_shell("executor", executor, 1)
    executor_gzip = _compress("executor", executor, gzip_compressor)
    capture_wrapper = _render_once(
        "capture_wrapper",
        CAPTURE_WRAPPER_TEMPLATE,
        {
            b"@@GZIP_BYTES@@": str(len(executor_gzip)).encode("ascii"),
            b"@@GZIP_SHA256@@": _sha256(executor_gzip).encode("ascii"),
            b"@@RAW_BYTES@@": str(len(executor)).encode("ascii"),
            b"@@RAW_SHA256@@": _sha256(executor).encode("ascii"),
            b"@@GZIP_B85@@": _b85("executor", executor_gzip),
        },
    )
    _validate_shell("capture_wrapper", capture_wrapper, 1)
    artifacts = {
        "capture": capture,
        "capture_gzip": capture_gzip,
        "control_envelope": control_envelope,
        "executor": executor,
        "executor_gzip": executor_gzip,
        "capture_wrapper": capture_wrapper,
    }
    sizing = {name: _layer(artifacts[name]) for name in SUMMARY_LAYER_NAMES}
    sizing["capture_command_content"] = _command(
        "capture_command_content",
        capture_wrapper,
    )
    return {"artifacts": artifacts, "sizing": sizing}


def _render_item26_restored_v1_transport_for_test(
    control_envelope: bytes,
    recipient_public_key_sha256: str,
    builder_identity_sha256: str,
    source_manifest_bytes: int,
    source_manifest_file_sha256: str,
    source_manifest_sha256: str,
    restored_topology_sha256: str,
    storage_config_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    result = _render_core(
        control_envelope,
        recipient_public_key_sha256,
        builder_identity_sha256,
        source_manifest_bytes,
        source_manifest_file_sha256,
        source_manifest_sha256,
        restored_topology_sha256,
        storage_config_sha256,
        gzip_compressor=gzip_compressor,
    )
    return {
        "artifacts": result["artifacts"],
        "mode": "TEST_SIZING_ONLY",
        "sizing": result["sizing"],
    }


def _production_provenance() -> dict[str, object]:
    return {
        "gzip_arguments": ["-9", "-n", "-c"],
        "gzip_implementation": "GNU",
        "platform": "linux",
        "templates": {
            name: dict(identity)
            for name, identity in TEMPLATE_IDENTITIES.items()
        },
    }


def render_item26_restored_v1_transport(
    control_envelope: bytes,
    recipient_public_key_sha256: str,
    builder_identity_sha256: str,
    source_manifest_bytes: int,
    source_manifest_file_sha256: str,
    source_manifest_sha256: str,
    restored_topology_sha256: str,
    storage_config_sha256: str,
) -> dict[str, object]:
    """Render only on Linux with GNU gzip; all inputs are Secret-free."""

    try:
        compressor = v3._production_gzip_compressor()
    except v3.RenderError as exc:
        raise RenderError(exc.code) from exc
    result = _render_core(
        control_envelope,
        recipient_public_key_sha256,
        builder_identity_sha256,
        source_manifest_bytes,
        source_manifest_file_sha256,
        source_manifest_sha256,
        restored_topology_sha256,
        storage_config_sha256,
        gzip_compressor=compressor,
    )
    summary = dict(result["sizing"])
    summary["production_provenance"] = _production_provenance()
    summary["public_bindings"] = {
        "builder_identity_sha256": builder_identity_sha256,
        "control_envelope_bytes": len(control_envelope),
        "control_envelope_sha256": _sha256(control_envelope),
        "recipient_public_key_sha256": recipient_public_key_sha256,
        "restored_topology_sha256": restored_topology_sha256,
        "source_manifest_bytes": source_manifest_bytes,
        "source_manifest_file_sha256": source_manifest_file_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "storage_config_sha256": storage_config_sha256,
    }
    canonical_summary(summary)
    return {"artifacts": result["artifacts"], "summary": summary}


def canonical_summary(summary: dict[str, object]) -> bytes:
    if type(summary) is not dict or set(summary) != SUMMARY_KEYS:
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
    command_targets = {"capture_command_content": "capture_wrapper"}
    for command_name, target_name in command_targets.items():
        command = summary.get(command_name)
        if (
            type(command) is not dict
            or set(command) != {"base64", "bytes", "sha256"}
            or type(command.get("base64")) is not str
            or type(command.get("bytes")) is not int
            or not 1 <= command["bytes"] <= MAX_COMMAND_CONTENT_BYTES
            or type(command.get("sha256")) is not str
            or HEX64.fullmatch(command["sha256"]) is None
        ):
            raise RenderError("summary_contract")
        try:
            encoded = command["base64"].encode("ascii")
            decoded = base64.b64decode(encoded, validate=True)
        except BaseException as exc:
            raise RenderError("summary_contract") from exc
        if (
            len(encoded) != command["bytes"]
            or _sha256(encoded) != command["sha256"]
            or len(decoded) != summary[target_name]["bytes"]
            or _sha256(decoded) != summary[target_name]["sha256"]
        ):
            raise RenderError("summary_contract")
    public = summary.get("public_bindings")
    if type(public) is not dict or set(public) != {
        "builder_identity_sha256",
        "control_envelope_bytes",
        "control_envelope_sha256",
        "recipient_public_key_sha256",
        "restored_topology_sha256",
        "source_manifest_bytes",
        "source_manifest_file_sha256",
        "source_manifest_sha256",
        "storage_config_sha256",
    }:
        raise RenderError("summary_contract")
    for key in (
        "builder_identity_sha256",
        "control_envelope_sha256",
        "recipient_public_key_sha256",
        "restored_topology_sha256",
        "source_manifest_file_sha256",
        "source_manifest_sha256",
        "storage_config_sha256",
    ):
        _validate_hash(public.get(key), "summary_contract")
    if (
        type(public.get("control_envelope_bytes")) is not int
        or not 1 <= public["control_envelope_bytes"] <= MAX_CONTROL_ENVELOPE_BYTES
        or public["control_envelope_bytes"] != summary["control_envelope"]["bytes"]
        or public["control_envelope_sha256"] != summary["control_envelope"]["sha256"]
        or type(public.get("source_manifest_bytes")) is not int
        or not 1 <= public["source_manifest_bytes"] <= MAX_SOURCE_MANIFEST_BYTES
        or summary.get("production_provenance") != _production_provenance()
    ):
        raise RenderError("summary_contract")
    try:
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
    except BaseException as exc:
        raise RenderError("summary_canonical") from exc
    if json.loads(body.decode("ascii")) != summary:
        raise RenderError("summary_canonical")
    return body


def _write_all(descriptor: int, body: bytes) -> bool:
    return v3._write_all(descriptor, body)


def _cli() -> int:
    try:
        request_body = sys.stdin.buffer.read(65537)
        if not request_body or len(request_body) > 65536:
            raise RenderError("request_size")
        request = json.loads(request_body.decode("ascii"), object_pairs_hook=_no_duplicates)
        expected = {
            "builder_identity_sha256",
            "control_envelope_base64",
            "recipient_public_key_sha256",
            "restored_topology_sha256",
            "source_manifest_bytes",
            "source_manifest_file_sha256",
            "source_manifest_sha256",
            "storage_config_sha256",
        }
        if type(request) is not dict or set(request) != expected:
            raise RenderError("request_contract")
        envelope = base64.b64decode(
            request["control_envelope_base64"],
            validate=True,
        )
        result = render_item26_restored_v1_transport(
            envelope,
            request["recipient_public_key_sha256"],
            request["builder_identity_sha256"],
            request["source_manifest_bytes"],
            request["source_manifest_file_sha256"],
            request["source_manifest_sha256"],
            request["restored_topology_sha256"],
            request["storage_config_sha256"],
        )
        output = canonical_summary(result["summary"])
    except RenderError as exc:
        _write_all(2, ("ITEM26_RESTORED_V1_RENDER_FAILED:" + exc.code + "\n").encode("ascii"))
        return 2
    except BaseException:
        _write_all(2, b"ITEM26_RESTORED_V1_RENDER_FAILED:internal\n")
        return 2
    return 0 if _write_all(1, output) else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
