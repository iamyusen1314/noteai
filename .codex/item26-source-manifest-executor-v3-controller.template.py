import base64
import gzip
import hashlib
import json
import os
import re
import subprocess


EXECUTOR_GZIP_BYTES = @@EXECUTOR_GZIP_BYTES@@
EXECUTOR_GZIP_SHA256 = "@@EXECUTOR_GZIP_SHA256@@"
EXECUTOR_BYTES = @@EXECUTOR_BYTES@@
EXECUTOR_SHA256 = "@@EXECUTOR_SHA256@@"
EXECUTOR_GZIP_B85 = b"@@EXECUTOR_GZIP_B85@@"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
B85 = re.compile(br"^[0-9A-Za-z!#$%&()*+\-;<=>?@^_`{|}~]+$")
PHASE = re.compile(r"^[a-z0-9_]{1,64}$")
PASS_KEY_TEXT = "NOTEAI_ITEM26_SOURCE_MANIFEST,incident_class,transaction,manifest_bytes,manifest_file_sha256,manifest_sha256,postgresql_major_version,table_count,migration_count,object_count,object_size_bytes,database_connection_count,database_transaction_count,database_write_count,object_write_count,row_values_emitted,object_keys_emitted,object_contents_read,secret_values_emitted,executor_native_superuser,managed_owner_activation_count,owner_table_contract_exact,owner_mismatch_count,rls_contract_exact,rls_table_count,force_rls_table_count,row_security_off,persistent_permission_mutation_count,runtime_container_start_count,container_residue_count,task_root_residue_count,source_manifest_retained,temporary_account_delete_required,provider_control_plane_mutation_count,registry_call_count,automatic_retry_allowed,transfer_state,transfer_retained,readback_required"
PASS_KEYS = frozenset(PASS_KEY_TEXT.split(","))
FAILURE_KEYS = frozenset("NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR,incident_class,phase,database_attempted_state,transfer_state,readback_required,automatic_retry_allowed".split(","))


class WrapperError(Exception):
    def __init__(self, phase, spawned=False):
        Exception.__init__(self, phase)
        self.phase = phase
        self.spawned = spawned


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def fixed(status, phase):
    if status == "FAIL":
        return {
            "NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR_WRAPPER": "FAIL",
            "incident_class": "PRE_CONNECT",
            "phase": phase,
            "executor_spawned": False,
            "database_attempted_state": "NO",
            "readback_required": False,
            "automatic_retry_allowed": False,
        }
    return {
        "NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR_WRAPPER": "UNKNOWN",
        "incident_class": "CONNECTED_UNKNOWN",
        "phase": phase,
        "executor_spawned": True,
        "database_attempted_state": "UNKNOWN",
        "readback_required": True,
        "automatic_retry_allowed": False,
    }


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def validate_terminal(returncode, stdout, stderr):
    if len(stdout) + len(stderr) > 4096:
        raise WrapperError("executor_output_limit", True)
    if returncode == 0:
        if not stdout or stderr:
            raise WrapperError("executor_pass_stream", True)
        stream = 1
        body = stdout
    elif returncode in (3, 4):
        if stdout or not stderr:
            raise WrapperError("executor_failure_stream", True)
        stream = 2
        body = stderr
    else:
        raise WrapperError("executor_returncode", True)
    if not body.endswith(b"\n") or body.count(b"\n") != 1:
        raise WrapperError("executor_output_shape", True)
    try:
        value = json.loads(
            body.decode("ascii"),
            object_pairs_hook=no_duplicates,
        )
    except BaseException:
        raise WrapperError("executor_output_json", True)
    if not isinstance(value, dict) or canonical(value) != body:
        raise WrapperError("executor_output_canonical", True)
    if value.get("automatic_retry_allowed") is not False:
        raise WrapperError("executor_retry_contract", True)
    if returncode == 0:
        if set(value) != PASS_KEYS:
            raise WrapperError("executor_pass_contract", True)
        if (
            value.get("NOTEAI_ITEM26_SOURCE_MANIFEST") != "PASS"
            or value.get("incident_class") != "CONNECTED_KNOWN_READ_ONLY"
            or value.get("transaction") != "REPEATABLE_READ_READ_ONLY_ROLLBACK"
            or value.get("transfer_state") != "EXACT_RETAINED"
            or any(type(value.get(key)) is not int or value[key] != expected for key, expected in zip((
                "postgresql_major_version", "table_count", "migration_count",
                "database_connection_count", "database_transaction_count",
                "database_write_count", "object_write_count", "row_values_emitted",
                "object_keys_emitted", "object_contents_read", "secret_values_emitted",
                "managed_owner_activation_count", "owner_mismatch_count",
                "rls_table_count", "force_rls_table_count",
                "persistent_permission_mutation_count", "runtime_container_start_count",
                "container_residue_count", "task_root_residue_count",
                "provider_control_plane_mutation_count", "registry_call_count",
            ), (16,56,17,1,1,0,0,0,0,0,0,1,0,19,0,0,1,0,0,0,0)))
            or any(value.get(key) is not expected for key, expected in zip((
                "executor_native_superuser", "owner_table_contract_exact",
                "rls_contract_exact", "row_security_off", "source_manifest_retained",
                "temporary_account_delete_required", "automatic_retry_allowed",
                "transfer_retained", "readback_required",
            ), (False,True,True,True,True,True,False,True,True)))
        ):
            raise WrapperError("executor_pass_contract", True)
        for key, minimum, maximum in (
            ("manifest_bytes", 1, 1048576),
            ("object_count", 0, 100000),
            ("object_size_bytes", 0, 1000000000000000),
        ):
            supplied = value.get(key)
            if type(supplied) is not int or not minimum <= supplied <= maximum:
                raise WrapperError("executor_pass_contract", True)
        for key in ("manifest_file_sha256", "manifest_sha256"):
            if type(value.get(key)) is not str or HEX64.fullmatch(value[key]) is None:
                raise WrapperError("executor_pass_contract", True)
    else:
        if set(value) != FAILURE_KEYS:
            raise WrapperError("executor_failure_contract", True)
        expected = "FAIL" if returncode == 3 else "UNKNOWN"
        incident = "PRE_CONNECT" if returncode == 3 else "CONNECTED_UNKNOWN"
        attempted = "NO" if returncode == 3 else "UNKNOWN"
        readback = False if returncode == 3 else True
        if (
            value.get("NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR") != expected
            or value.get("incident_class") != incident
            or value.get("database_attempted_state") != attempted
            or value.get("readback_required") is not readback
            or type(value.get("automatic_retry_allowed")) is not bool
            or value.get("automatic_retry_allowed") is not False
            or type(value.get("phase")) is not str
            or PHASE.fullmatch(value["phase"]) is None
            or (
                returncode == 3
                and value.get("transfer_state") not in {
                    "UNVERIFIED", "UNVERIFIED_RETAINED", "EXACT_RETAINED",
                }
            )
            or (returncode == 4 and value.get("transfer_state") != "UNKNOWN")
        ):
            raise WrapperError("executor_failure_contract", True)
    return stream, body


def main():
    if os.geteuid() != 0 or os.getegid() != 0:
        raise WrapperError("identity")
    if (
        type(EXECUTOR_GZIP_BYTES) is not int
        or type(EXECUTOR_BYTES) is not int
        or not 1 <= EXECUTOR_GZIP_BYTES <= 131072
        or not 1 <= EXECUTOR_BYTES <= 131072
        or HEX64.fullmatch(EXECUTOR_GZIP_SHA256) is None
        or HEX64.fullmatch(EXECUTOR_SHA256) is None
        or B85.fullmatch(EXECUTOR_GZIP_B85) is None
        or len(EXECUTOR_GZIP_B85) != (EXECUTOR_GZIP_BYTES * 5 + 3) // 4
    ):
        raise WrapperError("binding")
    try:
        compressed = base64.b85decode(EXECUTOR_GZIP_B85)
    except BaseException:
        raise WrapperError("decode")
    if (
        len(compressed) != EXECUTOR_GZIP_BYTES
        or hashlib.sha256(compressed).hexdigest() != EXECUTOR_GZIP_SHA256
    ):
        raise WrapperError("gzip_hash")
    try:
        raw = gzip.decompress(compressed)
    except BaseException:
        raise WrapperError("gzip")
    if len(raw) != EXECUTOR_BYTES or hashlib.sha256(raw).hexdigest() != EXECUTOR_SHA256:
        raise WrapperError("executor_hash")
    try:
        process = subprocess.Popen(
            ["/bin/bash", "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LC_ALL": "C",
            },
            close_fds=True,
            bufsize=0,
            start_new_session=True,
        )
    except BaseException:
        raise WrapperError("executor_spawn")
    try:
        stdout, stderr = process.communicate(raw)
    except BaseException:
        raise WrapperError("executor_communicate", True)
    returncode = process.returncode
    return returncode, validate_terminal(returncode, stdout, stderr)


try:
    exit_code, terminal = main()
except WrapperError as exc:
    exit_code = 4 if exc.spawned else 3
    terminal = (2, canonical(fixed("UNKNOWN" if exc.spawned else "FAIL", exc.phase)))
except BaseException:
    exit_code = 4
    terminal = (2, canonical(fixed("UNKNOWN", "wrapper_exception")))
stream, body = terminal
if len(body) > 4096:
    os._exit(4)
try:
    written = os.write(stream, body)
    if written != len(body):
        os._exit(4)
except BaseException:
    os._exit(4)
os._exit(exit_code)
