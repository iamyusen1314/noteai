#!/usr/bin/env python3
"""Render the inert, exact Item 29 API-C capacity-controller request.

The renderer is intentionally BLOCKED while the versioned Item 28 dependency
authority is empty.  After Item 28 freezes, those five fields can be bound
mechanically without renaming or guessing an Item 28 evidence artifact.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
DEPENDENCY_SCHEMA = "noteai.item29.item28-dependency.v1"
ACTION = "capacity_controller"
REGION = "cn-shenzhen"
COMMAND_NAME = "noteai-item29-capacity-100-controller-20260814-v1"
TASK_TAG = ("noteai-task", "item29-capacity-100-v1")
EXECUTOR_REF = "deploy/production/capacity_100_jobs.py"
EXECUTOR_BYTES = 19237
EXECUTOR_SHA256 = "ad9b7e219c9129ed919d2b3dcb966fbfa710400ea5e05335bc87daceb0e75343"
PROVIDER_TIMEOUT_SECONDS = 1800
MAX_INPUT_BYTES = 65536
MAX_COMMAND_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Mechanical binding interface.  Empty values are the current source truth and
# deliberately prevent rendering until Item 28's terminal checkpoint exists.
FROZEN_ITEM28_DEPENDENCY = {
    "schema": DEPENDENCY_SCHEMA,
    "authority_root": "",
    "verifier_path": "",
    "verifier_sha256": "",
    "evidence_path": "",
    "evidence_sha256": "",
    "receipt_path": "",
    "receipt_sha256": "",
    "checkpoint_path": "",
    "checkpoint_sha256": "",
    "terminal_acceptance_sha256": "",
}
# The host-bound Worker-C/Worker-F production adapter is deliberately absent
# from this source-only checkpoint.  A future adapter must be independently
# frozen before rendering can become possible.
PRODUCTION_RUNTIME_ADAPTER_BOUND = False

INPUT_KEYS = {
    "action", "plan_nonce", "api_c_instance_id", "item28_dependency",
}
RUN_COMMAND_KEYS = {
    "ClientToken", "CommandContent", "ContentEncoding", "EnableParameter",
    "InstanceId", "KeepCommand", "Name", "RegionId", "RepeatMode", "Tag",
    "TerminationMode", "Timeout", "Type", "Username", "WorkingDir",
}


class RequestError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical(value):
    try:
        return (json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RequestError("json") from exc


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RequestError("duplicate_json_key")
        value[key] = item
    return value


def parse_canonical(raw):
    if (
        type(raw) is not bytes or not 1 <= len(raw) <= MAX_INPUT_BYTES
        or not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw
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


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _dependency_complete(value):
    return bool(
        type(value) is dict
        and set(value) == set(FROZEN_ITEM28_DEPENDENCY)
        and value.get("schema") == DEPENDENCY_SCHEMA
        and type(value.get("verifier_path")) is str
        and value["verifier_path"].startswith("tools/")
        and all(
            type(value.get(key)) is str
            and value[key].startswith("deploy/production/evidence/")
            for key in ("evidence_path", "receipt_path", "checkpoint_path")
        )
        and all(
            type(value.get(key)) is str and HEX64.fullmatch(value[key]) is not None
            for key in (
                "authority_root", "verifier_sha256", "evidence_sha256",
                "receipt_sha256", "checkpoint_sha256",
                "terminal_acceptance_sha256",
            )
        )
    )


def validate_input(value):
    if type(value) is not dict or set(value) != INPUT_KEYS:
        raise RequestError("input_contract")
    if value.get("action") != ACTION:
        raise RequestError("action")
    if type(value.get("plan_nonce")) is not str or UUID.fullmatch(
        value["plan_nonce"]
    ) is None:
        raise RequestError("plan_nonce")
    if type(value.get("api_c_instance_id")) is not str or INSTANCE_ID.fullmatch(
        value["api_c_instance_id"]
    ) is None:
        raise RequestError("api_c_instance_id")
    if not _dependency_complete(FROZEN_ITEM28_DEPENDENCY):
        raise RequestError("item28_dependency_authority_not_frozen")
    if canonical(value.get("item28_dependency")) != canonical(
        FROZEN_ITEM28_DEPENDENCY
    ):
        raise RequestError("item28_dependency_binding")
    if PRODUCTION_RUNTIME_ADAPTER_BOUND is not True:
        raise RequestError("production_runtime_adapter_not_frozen")
    return value["api_c_instance_id"]


def _stable(row):
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def read_executor(root=ROOT):
    if EXECUTOR_BYTES <= 0 or HEX64.fullmatch(EXECUTOR_SHA256) is None:
        raise RequestError("executor_authority_not_frozen")
    path = root / EXECUTOR_REF
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o644 or before.st_nlink != 1
        ):
            raise RequestError("executor_identity")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise RequestError("executor_identity")
            raw = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 256 * 1024:
                    raise RequestError("executor_identity")
        finally:
            os.close(fd)
        after = path.lstat()
    except RequestError:
        raise
    except OSError as exc:
        raise RequestError("executor_identity") from exc
    if (
        _stable(before) != _stable(after)
        or len(raw) != EXECUTOR_BYTES
        or _sha(raw) != EXECUTOR_SHA256
    ):
        raise RequestError("executor_identity")
    return raw


def _gzip(raw):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as handle:
        handle.write(raw)
    return output.getvalue()


def derive_client_token(value):
    validate_input(value)
    return _sha(
        b"noteai-item29-capacity-100-v1\x00"
        + canonical({
            "action": value["action"],
            "plan_nonce": value["plan_nonce"],
            "item28_dependency": value["item28_dependency"],
        })
    )


def render_wrapper(executor, value):
    compressed = _gzip(executor)
    source_sha = _sha(executor)
    compressed_sha = _sha(compressed)
    encoded = base64.b64encode(compressed).decode("ascii")
    dependency = base64.b64encode(
        canonical(value["item28_dependency"])[:-1]
    ).decode("ascii")
    wrapper = f"""#!/bin/sh
set -eu
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C LANG=C
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset ANTHROPIC_API_KEY MOONSHOT_API_KEY KIMI_API_KEY
run_dir=/run/.noteai-item29-capacity.$$
run_dir_owned=0
src_created=0
gz_created=0
out_created=0
err_created=0
src=$run_dir/payload.py
gz=$run_dir/payload.py.gz
out=$run_dir/payload.stdout
err=$run_dir/payload.stderr
cleanup() {{
    if [ "$run_dir_owned" -ne 1 ]; then
        return 0
    fi
    if [ "$src_created" -eq 1 ]; then /bin/rm -f -- "$src"; fi
    if [ "$gz_created" -eq 1 ]; then /bin/rm -f -- "$gz"; fi
    if [ "$out_created" -eq 1 ]; then /bin/rm -f -- "$out"; fi
    if [ "$err_created" -eq 1 ]; then /bin/rm -f -- "$err"; fi
    /bin/rmdir -- "$run_dir" 2>/dev/null || :
}}
trap cleanup EXIT HUP INT TERM
/bin/mkdir -m 0700 -- "$run_dir"
run_dir_owned=1
( set -C; : > "$src" )
src_created=1
( set -C; : > "$gz" )
gz_created=1
( set -C; : > "$out" )
out_created=1
( set -C; : > "$err" )
err_created=1
chmod 0700 "$src"
printf '%s' '{encoded}' | /usr/bin/base64 -d > "$gz"
[ "$(/usr/bin/sha256sum "$gz" | /usr/bin/awk '{{print $1}}')" = '{compressed_sha}' ]
/usr/bin/gzip -dc "$gz" > "$src"
[ "$(/usr/bin/sha256sum "$src" | /usr/bin/awk '{{print $1}}')" = '{source_sha}' ]
dep=$(/usr/bin/printf '%s' '{dependency}' | /usr/bin/base64 -d)
set +e
/usr/bin/python3 -I "$src" --runtime-factory __main__:create_runtime --plan-nonce '{value['plan_nonce']}' --item28-dependency-json "$dep" > "$out" 2> "$err"
rc=$?
set -e
out_b64=$(/usr/bin/base64 < "$out" | /usr/bin/tr -d '\\n')
err_b64=$(/usr/bin/base64 < "$err" | /usr/bin/tr -d '\\n')
cleanup
[ ! -e "$src" ]
[ ! -e "$gz" ]
[ ! -e "$out" ]
[ ! -e "$err" ]
[ ! -e "$run_dir" ]
trap - EXIT HUP INT TERM
/usr/bin/printf '%s' "$out_b64" | /usr/bin/base64 -d
/usr/bin/printf '%s' "$err_b64" | /usr/bin/base64 -d >&2
exit "$rc"
""".encode("ascii")
    if len(wrapper) > MAX_COMMAND_CONTENT_BYTES:
        raise RequestError("command_too_large")
    return wrapper


def render_request(value, root=ROOT):
    target = validate_input(value)
    executor = read_executor(root)
    wrapper = render_wrapper(executor, value)
    request = {
        "ClientToken": derive_client_token(value),
        "CommandContent": base64.b64encode(wrapper).decode("ascii"),
        "ContentEncoding": "Base64",
        "EnableParameter": False,
        "InstanceId": [target],
        "KeepCommand": True,
        "Name": COMMAND_NAME,
        "RegionId": REGION,
        "RepeatMode": "Once",
        "Tag": [{"Key": TASK_TAG[0], "Value": TASK_TAG[1]}],
        "TerminationMode": "ProcessTree",
        "Timeout": PROVIDER_TIMEOUT_SECONDS,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    if set(request) != RUN_COMMAND_KEYS:
        raise RequestError("request_schema")
    return request, {
        "action": ACTION,
        "name": COMMAND_NAME,
        "target_count": 1,
        "executor_sha256": EXECUTOR_SHA256,
        "item28_dependency_schema": DEPENDENCY_SCHEMA,
        "automatic_retry_allowed": False,
        "same_request_resubmit_allowed": False,
        "provider_client_token_readback_supported": False,
        "provider_history_key": "Name",
        "wrapper_child_exec_used": False,
        "wrapper_cleanup_requires_owned_private_directory": True,
        "wrapper_host_temp_file_count": 4,
        "wrapper_private_directory_atomic_mkdir": True,
        "wrapper_temp_file_created_flag_count": 4,
        "wrapper_temp_residue_absence_audited_before_output": True,
        "production_runtime_adapter_bound": True,
    }


def main(argv=None):
    del argv
    try:
        value = parse_canonical(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
        request, _validation = render_request(value)
    except RequestError as exc:
        code = exc.code if isinstance(exc, RequestError) else "input_json"
        sys.stderr.write(code + "\n")
        return 3
    sys.stdout.buffer.write(canonical(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
