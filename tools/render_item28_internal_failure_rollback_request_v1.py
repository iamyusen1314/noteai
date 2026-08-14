#!/usr/bin/env python3
"""Render the one exact, no-replay Item 28 Cloud Assistant request locally."""

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
from types import MappingProxyType


REGION = "cn-shenzhen"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
TASK_TAG = ("noteai-task", "item28-internal-rollback-v1")
ACTION = "api_f_rollback"
COMMAND_NAME = "noteai-item28-internal-rollback-api-f-20260814-v1"
HOST_MODE = "api-f"
PROVIDER_TIMEOUT_SECONDS = 960
MAX_INPUT_BYTES = 65536
MAX_COMMAND_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_REF = "deploy/production/internal_failure_rollback.py"
EXECUTOR_IDENTITY = MappingProxyType({
    "bytes": 41841,
    "sha256": "5f233668966bef323d036393ab21a0f1f67d3e935a38e766e857a4110dcb5499",
    "mode": 0o644,
})
INPUT_KEYS = frozenset({
    "action", "plan_nonce", "api_f_instance_id",
    "item25_terminal_acceptance_sha256",
    "item26_terminal_acceptance_sha256",
    "item27_terminal_acceptance_sha256",
})
RUN_COMMAND_KEYS = frozenset({
    "ClientToken", "CommandContent", "ContentEncoding", "EnableParameter",
    "InstanceId", "KeepCommand", "Name", "RegionId", "RepeatMode", "Tag",
    "TerminationMode", "Timeout", "Type", "Username", "WorkingDir",
})


class RequestError(ValueError):
    def __init__(self, code):
        ValueError.__init__(self, code)
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


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_input(value):
    if type(value) is not dict or set(value) != INPUT_KEYS:
        raise RequestError("input_contract")
    if value["action"] != ACTION:
        raise RequestError("action")
    if type(value["plan_nonce"]) is not str or HEX32.fullmatch(value["plan_nonce"]) is None:
        raise RequestError("plan_nonce")
    target = value["api_f_instance_id"]
    if type(target) is not str or INSTANCE_ID.fullmatch(target) is None:
        raise RequestError("api_f_instance_id")
    predecessors = {}
    for item in ("item25", "item26", "item27"):
        key = item + "_terminal_acceptance_sha256"
        digest = value[key]
        if type(digest) is not str or HEX64.fullmatch(digest) is None:
            raise RequestError(key)
        predecessors[item] = digest
    if len(set(predecessors.values())) != 3:
        raise RequestError("predecessors_distinct")
    return target, predecessors


def derive_client_token(value):
    _target, predecessors = validate_input(value)
    payload = (
        b"noteai-item28-internal-rollback-v1\x00"
        + value["plan_nonce"].encode("ascii") + b"\x00"
        + b"\x00".join(
            item.encode("ascii") + b"=" + predecessors[item].encode("ascii")
            for item in ("item25", "item26", "item27")
        )
        + b"\x00" + ACTION.encode("ascii")
    )
    return _sha256(payload)


def _stable(row):
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def read_executor(root=ROOT):
    path = root / EXECUTOR_REF
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or stat.S_IMODE(before.st_mode) != EXECUTOR_IDENTITY["mode"]
            or before.st_nlink != 1
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
        or len(raw) != EXECUTOR_IDENTITY["bytes"]
        or _sha256(raw) != EXECUTOR_IDENTITY["sha256"]
    ):
        raise RequestError("executor_identity")
    return raw


def gzip_exact(raw):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as handle:
        handle.write(raw)
    return output.getvalue()


def render_wrapper(executor):
    compressed = gzip_exact(executor)
    encoded = base64.b64encode(compressed).decode("ascii")
    source_sha = _sha256(executor)
    compressed_sha = _sha256(compressed)
    wrapper = f"""#!/bin/sh
set -eu
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C LANG=C
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset DATABASE_URL DOCKER_HOST DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY
task_dir=/run/.noteai-item28-wrapper.$$
owned=0
src="$task_dir/executor.py"
gz="$task_dir/executor.py.gz"
out="$task_dir/stdout"
err="$task_dir/stderr"
cleanup() {{
  if [ "$owned" -eq 1 ]; then
    rm -f -- "$src" "$gz" "$out" "$err"
    rmdir -- "$task_dir" || true
    owned=0
  fi
}}
trap cleanup EXIT HUP INT TERM
if ! /bin/mkdir -m 0700 -- "$task_dir"; then exit 4; fi
owned=1
( set -C; : > "$src"; : > "$gz"; : > "$out"; : > "$err" )
chmod 0700 "$src"
printf '%s' '{encoded}' | /usr/bin/base64 -d > "$gz"
[ "$(/usr/bin/sha256sum "$gz" | /usr/bin/awk '{{print $1}}')" = '{compressed_sha}' ]
/usr/bin/gzip -dc "$gz" > "$src"
[ "$(/usr/bin/sha256sum "$src" | /usr/bin/awk '{{print $1}}')" = '{source_sha}' ]
set +e
/usr/bin/python3 -I "$src" --mode api-f >"$out" 2>"$err"
rc=$?
set -e
case "$rc" in
  0) [ ! -s "$err" ]; /bin/cat "$out" ;;
  3|4) [ ! -s "$out" ]; /bin/cat "$err" >&2 ;;
  *) exit 4 ;;
esac
exit "$rc"
""".encode("ascii")
    if len(wrapper) > MAX_COMMAND_CONTENT_BYTES:
        raise RequestError("command_too_large")
    return wrapper, compressed


def render_request(value, root=ROOT):
    target, _predecessors = validate_input(value)
    executor = read_executor(root)
    wrapper, compressed = render_wrapper(executor)
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
    validation = validate_run_command(request, value, root=root)
    validation.update({
        "compressed_executor_bytes": len(compressed),
        "compressed_executor_sha256": _sha256(compressed),
    })
    return request, validation


def validate_run_command(request, renderer_input, root=ROOT):
    target, predecessors = validate_input(renderer_input)
    if type(request) is not dict or set(request) != RUN_COMMAND_KEYS:
        raise RequestError("request_schema")
    executor = read_executor(root)
    wrapper, _compressed = render_wrapper(executor)
    expected = {
        "ClientToken": derive_client_token(renderer_input),
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
    if canonical(request) != canonical(expected):
        raise RequestError("request_binding")
    if type(request["Timeout"]) is not int or type(request["EnableParameter"]) is not bool:
        raise RequestError("request_types")
    return {
        "action": ACTION,
        "name": COMMAND_NAME,
        "host_mode": HOST_MODE,
        "target_count": 1,
        "client_token_sha256": _sha256(request["ClientToken"].encode("ascii")),
        "command_content_bytes": len(wrapper),
        "command_content_sha256": _sha256(wrapper),
        "executor_bytes": len(executor),
        "executor_sha256": _sha256(executor),
        "predecessor_acceptance_sha256": predecessors,
        "automatic_retry_allowed": False,
        "same_request_resubmit_allowed": False,
        "provider_client_token_readback_supported": False,
    }


def main(argv=None):
    del argv
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        value = parse_canonical(raw)
        request, _validation = render_request(value)
        sys.stdout.buffer.write(canonical(request))
        return 0
    except RequestError as exc:
        sys.stderr.write(exc.code + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
