#!/usr/bin/env python3
"""Render exact write-once Item 29 SendFile and one-shot phase requests."""

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
REGION = "cn-shenzhen"
EXECUTOR_REF = "deploy/production/capacity_100_jobs.py"
EXECUTOR_BYTES = 65429
EXECUTOR_SHA256 = "ee4b00f4286332712fa70ec81150ad81c13eaa292a58721b82e5b8430d4be311"
IMAGE = (
    "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@"
    "sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
)
IMAGE_CONFIG = "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
C17_REVISION = "cad5ce35664f617c6e19f90a6159285ddf975594"
API_C_INSTANCE = "i-wz9j36od3nf2b1uw7bvg"
WORKER_C_INSTANCE = "i-wz98zwcdtcmxzmmoso3w"
WORKER_F_INSTANCE = "i-wz93qgvlu1bllpjcfwfj"
DISPATCHER_UNIT_SHA256 = "8e2d9dc59b87585e5921f5c2b838db4c150efeebeb8e243e194bce586fc102fc"
WORKER_UNIT_SHA256 = "a3fa4407202620d5c3e0f6f1fd6de4babe564d3b0cea79c1cbded7a2e13fd200"
FROZEN_ITEM28_DEPENDENCY = {
    "schema": DEPENDENCY_SCHEMA,
    "evidence_path": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
    "evidence_sha256": (
        "429b41e4e7be1549181bed195623718ce65d2d052257ea176da99e266fa598f8"
    ),
    "terminal_acceptance_sha256": (
        "55363294b82f21c6c0fd000e8dcf08f481775a2f63b2a9dd733056ffb4f85c9c"
    ),
}
SOURCE_NAME = f"noteai-item29-capacity-{EXECUTOR_SHA256[:20]}.py.gz"
SOURCE_PATH = "/run/" + SOURCE_NAME
TASK_TAG = {"Key": "noteai-task", "Value": "item29-capacity-100-v1"}
MAX_INPUT_BYTES = 65536
MAX_COMMAND_CONTENT_BYTES = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

ACTION_SPECS = {
    "stage-api-c": ("send", API_C_INSTANCE, None, None),
    "stage-worker-c": ("send", WORKER_C_INSTANCE, None, None),
    "stage-worker-f": ("send", WORKER_F_INSTANCE, None, None),
    "preflight": ("run", API_C_INSTANCE, "preflight", None),
    "admit": ("run", API_C_INSTANCE, "admit", None),
    "admit-retry": ("run", API_C_INSTANCE, "admit", None),
    "resolve": ("run", API_C_INSTANCE, "resolve", None),
    "dispatch": ("run", API_C_INSTANCE, "dispatch", None),
    "dispatch-retry": ("run", API_C_INSTANCE, "dispatch", None),
    "dispatch-readback": ("run", API_C_INSTANCE, "dispatch-readback", None),
    "preclaim-c": ("run", WORKER_C_INSTANCE, "preclaim", "Worker-C"),
    "preclaim-f": ("run", WORKER_F_INSTANCE, "preclaim", "Worker-F"),
    "process-c": ("run", WORKER_C_INSTANCE, "process", "Worker-C"),
    "process-f": ("run", WORKER_F_INSTANCE, "process", "Worker-F"),
    "process-readback-c": (
        "run", WORKER_C_INSTANCE, "process-readback", "Worker-C"
    ),
    "process-readback-f": (
        "run", WORKER_F_INSTANCE, "process-readback", "Worker-F"
    ),
    "observe": ("run", API_C_INSTANCE, "observe", None),
    "cleanup": ("run", API_C_INSTANCE, "cleanup", None),
    "cleanup-retry": ("run", API_C_INSTANCE, "cleanup", None),
    "source-cleanup-worker-c": (
        "source-cleanup", WORKER_C_INSTANCE, None, "Worker-C"
    ),
    "source-cleanup-worker-f": (
        "source-cleanup", WORKER_F_INSTANCE, None, "Worker-F"
    ),
    "source-cleanup-api-c": (
        "source-cleanup", API_C_INSTANCE, None, "API-C"
    ),
}
NO_OPERATION_ACTIONS = {
    "stage-api-c", "stage-worker-c", "stage-worker-f",
    "preflight", "admit", "admit-retry", "resolve",
    "source-cleanup-worker-c", "source-cleanup-worker-f",
    "source-cleanup-api-c",
}
ALL_OPERATION_ACTIONS = {
    "dispatch-readback", "preclaim-c", "preclaim-f",
    "process-c", "process-f", "observe", "cleanup",
    "process-readback-c", "process-readback-f",
}
MUTATING_ACTIONS = {
    "admit", "admit-retry", "dispatch", "dispatch-retry", "preclaim-c", "preclaim-f",
    "process-c", "process-f", "cleanup",
    "cleanup-retry",
}
RUN_COMMAND_KEYS = {
    "ClientToken", "CommandContent", "ContentEncoding", "EnableParameter",
    "InstanceId", "KeepCommand", "Name", "RegionId", "RepeatMode", "Tag",
    "TerminationMode", "Timeout", "Type", "Username", "WorkingDir",
}
SEND_FILE_KEYS = {
    "Content", "ContentType", "Description", "FileGroup", "FileMode",
    "FileOwner", "InstanceId", "Name", "Overwrite", "RegionId", "Tag",
    "TargetDir",
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
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestError("duplicate_json_key")
        result[key] = value
    return result


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


def _gzip(raw):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as handle:
        handle.write(raw)
    return output.getvalue()


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
            or stat.S_IMODE(before.st_mode) != 0o644 or before.st_nlink != 1
        ):
            raise RequestError("executor_identity")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise RequestError("executor_identity")
            parts = []
            size = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 256 * 1024:
                    raise RequestError("executor_identity")
                parts.append(chunk)
        finally:
            os.close(fd)
        after = path.lstat()
    except RequestError:
        raise
    except OSError as exc:
        raise RequestError("executor_identity") from exc
    raw = b"".join(parts)
    if (
        _stable(before) != _stable(after) or len(raw) != EXECUTOR_BYTES
        or _sha(raw) != EXECUTOR_SHA256
    ):
        raise RequestError("executor_identity")
    return raw


def _valid_operations(action, values):
    if type(values) is not list:
        raise RequestError("operation_ids")
    if action in NO_OPERATION_ACTIONS:
        expected = {0}
    elif action in {"dispatch", "dispatch-retry"}:
        expected = set(range(1, 101))
    elif action in {"cleanup", "cleanup-retry"}:
        expected = set(range(101))
    else:
        expected = {100}
    if len(values) not in expected:
        raise RequestError("operation_ids_count")
    if any(type(value) is not str or UUID.fullmatch(value) is None for value in values):
        raise RequestError("operation_ids")
    if len(values) != len(set(values)):
        raise RequestError("operation_ids_duplicate")
    return list(values)


def validate_input(value):
    if type(value) is not dict or set(value) != {
        "action", "plan_nonce", "item28_dependency", "operation_ids",
    }:
        raise RequestError("input_contract")
    action = value.get("action")
    if type(action) is not str or action not in ACTION_SPECS:
        raise RequestError("action")
    if type(value.get("plan_nonce")) is not str or UUID.fullmatch(value["plan_nonce"]) is None:
        raise RequestError("plan_nonce")
    if value.get("item28_dependency") != FROZEN_ITEM28_DEPENDENCY:
        raise RequestError("item28_dependency_binding")
    operations = _valid_operations(action, value.get("operation_ids"))
    return action, operations


def derive_client_token(value):
    action, operations = validate_input(value)
    return _sha(
        b"noteai-item29-capacity-100-v1\x00" + canonical({
            "action": action,
            "plan_nonce": value["plan_nonce"],
            "operation_set_sha256": _sha(canonical(operations)),
        })
    )


def _service_contract(action):
    if action in {"dispatch", "dispatch-retry", "dispatch-readback"}:
        return (
            "/etc/noteai/ai-dispatcher.env",
            "/etc/systemd/system/noteai-ai-dispatcher.service",
            DISPATCHER_UNIT_SHA256,
            "dispatcher",
            "ai-worker",
            False,
        )
    if action in {
        "preclaim-c", "preclaim-f", "process-c", "process-f",
        "process-readback-c", "process-readback-f",
    }:
        return (
            "/etc/noteai/ai-worker.env",
            "/etc/systemd/system/noteai-ai-worker.service",
            WORKER_UNIT_SHA256,
            "worker",
            "ai-worker",
            action in {"process-c", "process-f"},
        )
    return (
        "/etc/noteai/api.env",
        "/etc/systemd/system/noteai-ai-dispatcher.service",
        DISPATCHER_UNIT_SHA256,
        "api",
        "api",
        action in {"admit", "admit-retry", "cleanup", "cleanup-retry"},
    )


def _source_cleanup_contract(action):
    if action == "source-cleanup-api-c":
        return (
            "/etc/systemd/system/noteai-ai-dispatcher.service",
            DISPATCHER_UNIT_SHA256,
            "dispatcher",
        )
    if action in {"source-cleanup-worker-c", "source-cleanup-worker-f"}:
        return (
            "/etc/systemd/system/noteai-ai-worker.service",
            WORKER_UNIT_SHA256,
            "worker",
        )
    raise RequestError("source_cleanup_action")


def render_source_cleanup(executor, value):
    action = value["action"]
    _kind, _target, _inner, host_label = ACTION_SPECS[action]
    unit_path, unit_sha, guarded_component = _source_cleanup_contract(action)
    source_gz_sha = _sha(_gzip(executor))
    if host_label == "API-C":
        allowed_names = (
            "/noteai-item29-preflight|/noteai-item29-admit|"
            "/noteai-item29-admit-retry|/noteai-item29-resolve|"
            "/noteai-item29-dispatch|/noteai-item29-dispatch-retry|"
            "/noteai-item29-dispatch-readback|/noteai-item29-observe|"
            "/noteai-item29-cleanup|/noteai-item29-cleanup-retry"
        )
    elif host_label == "Worker-C":
        allowed_names = (
            "/noteai-item29-preclaim-c|/noteai-item29-process-c|"
            "/noteai-item29-process-readback-c"
        )
    else:
        allowed_names = (
            "/noteai-item29-preclaim-f|/noteai-item29-process-f|"
            "/noteai-item29-process-readback-f"
        )
    wrapper = f"""#!/bin/sh
set -eu
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C LANG=C
src_gz='{SOURCE_PATH}'
unit='{unit_path}'
[ -f "$unit" ] && [ ! -L "$unit" ]
[ "$(/usr/bin/sha256sum "$unit" | /usr/bin/awk '{{print $1}}')" = '{unit_sha}' ]
[ "$(/bin/systemctl show -p ActiveState --value "$(/usr/bin/basename "$unit")")" = inactive ]
[ "$(/bin/systemctl show -p UnitFileState --value "$(/usr/bin/basename "$unit")")" = disabled ]
for guarded in noteai-ai-{guarded_component} noteai-ai-{guarded_component}-acceptance; do
  rows=$(/usr/bin/docker container ls -a --filter "name=^/${{guarded}}$" --format '{{{{.ID}}}}')
  [ -z "$rows" ]
done
task_removed=0
task_rows=$(/usr/bin/docker container ls -aq --no-trunc --filter label=noteai.task=item29-capacity-100-v1)
for cid in $task_rows; do
  [ "${{#cid}}" -eq 64 ]
  case "$cid" in (*[!0-9a-f]*|'') exit 1;; esac
  [ "$(/usr/bin/docker inspect -f '{{{{.Id}}}}' "$cid")" = "$cid" ]
  [ "$(/usr/bin/docker inspect -f '{{{{ index .Config.Labels "noteai.task" }}}}' "$cid")" = item29-capacity-100-v1 ]
  invocation=$(/usr/bin/docker inspect -f '{{{{ index .Config.Labels "noteai.invocation" }}}}' "$cid")
  [ "${{#invocation}}" -eq 32 ]
  case "$invocation" in (*[!0-9a-f]*|'') exit 1;; esac
  [ "$(/usr/bin/docker inspect -f '{{{{.State.Running}}}}' "$cid")" = false ]
  [ "$(/usr/bin/docker inspect -f '{{{{.Image}}}}' "$cid")" = '{IMAGE_CONFIG}' ]
  name=$(/usr/bin/docker inspect -f '{{{{.Name}}}}' "$cid")
  case "$name" in ({allowed_names}) :;; (*) exit 1;; esac
  /usr/bin/docker rm "$cid" >/dev/null
  ! /usr/bin/docker inspect "$cid" >/dev/null 2>&1
  task_removed=$((task_removed + 1))
done
run_removed=0
for run_dir in /run/.noteai-item29-capacity.*; do
  if [ ! -e "$run_dir" ] && [ ! -L "$run_dir" ]; then continue; fi
  suffix=${{run_dir#/run/.noteai-item29-capacity.}}
  case "$suffix" in (*[!0-9]*|'') exit 1;; esac
  [ -d "$run_dir" ] && [ ! -L "$run_dir" ]
  [ "$(/usr/bin/stat -c '%a:%u:%g' "$run_dir")" = '700:0:0' ]
  unexpected=$(/usr/bin/find "$run_dir" -mindepth 1 -maxdepth 1 \
    ! -name container.cid ! -name executor.py ! -name database.env \
    ! -name operations.json ! -name storage.env ! -name stdout \
    ! -name stderr -printf x -quit)
  [ -z "$unexpected" ]
  for leaf in container.cid executor.py database.env operations.json storage.env stdout stderr; do
    path="$run_dir/$leaf"
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then continue; fi
    [ -f "$path" ] && [ ! -L "$path" ]
    [ "$(/usr/bin/stat -c '%u:%g:%h' "$path")" = '0:0:1' ]
    mode=$(/usr/bin/stat -c '%a' "$path")
    case "$leaf:$mode" in
      container.cid:600|executor.py:600|executor.py:444|database.env:600|database.env:400|operations.json:600|operations.json:444|storage.env:600|storage.env:400|stdout:600|stderr:600) :;;
      (*) exit 1;;
    esac
    /bin/rm -f -- "$path"
  done
  /bin/rmdir -- "$run_dir"
  run_removed=$((run_removed + 1))
done
removed=0
if [ -e "$src_gz" ] || [ -L "$src_gz" ]; then
  [ -f "$src_gz" ] && [ ! -L "$src_gz" ]
  [ "$(/usr/bin/stat -c '%a:%u:%g:%h' "$src_gz")" = '400:0:0:1' ]
  [ "$(/usr/bin/sha256sum "$src_gz" | /usr/bin/awk '{{print $1}}')" = '{source_gz_sha}' ]
  /bin/rm -f "$src_gz"
  removed=1
fi
[ ! -e "$src_gz" ] && [ ! -L "$src_gz" ]
task_rows=$(/usr/bin/docker container ls -aq --no-trunc --filter label=noteai.task=item29-capacity-100-v1)
[ -z "$task_rows" ]
for run_dir in /run/.noteai-item29-capacity.*; do
  [ ! -e "$run_dir" ] && [ ! -L "$run_dir" ]
done
printf '{{"schema":"noteai.item29.source-cleanup.v1","action":"{action}","host":"{host_label}","status":"PASS","source_removed_count":%s,"source_residue_count":0,"task_container_removed_count":%s,"task_container_residue_count":0,"task_run_dir_removed_count":%s,"task_run_dir_residue_count":0}}\n' "$removed" "$task_removed" "$run_removed"
""".encode("ascii")
    if len(wrapper) > MAX_COMMAND_CONTENT_BYTES:
        raise RequestError("command_too_large")
    return wrapper


def render_wrapper(executor, value, operations):
    action = value["action"]
    _kind, _target, inner_phase, worker_name = ACTION_SPECS[action]
    env_source, unit_path, unit_sha, component, runtime_role, storage = (
        _service_contract(action)
    )
    operations_gz = _gzip(canonical(operations)[:-1])
    operations_encoded = base64.b64encode(operations_gz).decode("ascii")
    dependency_encoded = base64.b64encode(
        canonical(FROZEN_ITEM28_DEPENDENCY)[:-1]
    ).decode("ascii")
    source_gz_sha = _sha(_gzip(executor))
    storage_option = (
        '--env-file "$storage_env"'
        if storage else ""
    )
    storage_setup = ""
    if storage:
        storage_setup = """
storage_source=/etc/noteai/private-storage.env
[ -f "$storage_source" ] && [ ! -L "$storage_source" ]
[ "$(/usr/bin/stat -c '%a:%u:%g:%h' "$storage_source")" = '600:0:0:1' ]
for key in NOTEAI_PRIVATE_STORAGE_BACKEND NOTEAI_OSS_PRIVATE_BUCKET NOTEAI_OSS_REGION NOTEAI_OSS_ENDPOINT NOTEAI_OSS_RAM_ROLE NOTEAI_PRIVATE_STORAGE_KEY_EPOCH; do
  [ "$(/bin/grep -c "^$key=" "$storage_source")" -eq 1 ]
done
! /bin/grep -Eq '^(ANTHROPIC_API_KEY|MOONSHOT_API_KEY|KIMI_API_KEY|CLAUDE_API_KEY)=' "$storage_source"
/bin/grep -E '^(NOTEAI_PRIVATE_STORAGE_BACKEND|NOTEAI_OSS_PRIVATE_BUCKET|NOTEAI_OSS_REGION|NOTEAI_OSS_ENDPOINT|NOTEAI_OSS_RAM_ROLE|NOTEAI_PRIVATE_STORAGE_KEY_EPOCH|NOTEAI_OSS_KEY_PREFIX|NOTEAI_OSS_KMS_KEY_ID)=' "$storage_source" >"$storage_env"
chmod 0400 "$storage_env"
"""
    worker_option = f"--worker {worker_name}" if worker_name else ""
    mutation = TASK_ID if action in MUTATING_ACTIONS else "read-only"
    container_name = "noteai-item29-" + action
    host_label = worker_name or "API-C"
    invocation_label = derive_client_token(value)[:32]
    guarded_component = "worker" if component == "worker" else "dispatcher"
    wrapper = f"""#!/bin/sh
set -eu
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C LANG=C
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset ANTHROPIC_API_KEY MOONSHOT_API_KEY KIMI_API_KEY CLAUDE_API_KEY
src_gz='{SOURCE_PATH}'
unit='{unit_path}'
run_dir=/run/.noteai-item29-capacity.$$
container='{container_name}'
invocation='{invocation_label}'
owned=0
cidfile=$run_dir/container.cid
cleanup() {{
  if [ "$owned" -eq 1 ] && [ -f "$cidfile" ]; then
    cid=$(/bin/cat "$cidfile" 2>/dev/null || :)
    case "$cid" in (*[!0-9a-f]*|'') cid=invalid;; esac
    if [ "$cid" != invalid ] && /usr/bin/docker inspect "$cid" >/dev/null 2>&1; then
      actual=$(/usr/bin/docker inspect -f '{{{{.Id}}}}' "$cid" 2>/dev/null || :)
      task=$(/usr/bin/docker inspect -f '{{{{ index .Config.Labels \"noteai.task\" }}}}' "$cid" 2>/dev/null || :)
      bound=$(/usr/bin/docker inspect -f '{{{{ index .Config.Labels \"noteai.invocation\" }}}}' "$cid" 2>/dev/null || :)
      [ "$actual" = "$cid" ] && [ "$task" = item29-capacity-100-v1 ] && [ "$bound" = "$invocation" ] && /usr/bin/docker rm -f "$cid" >/dev/null 2>&1 || :
    fi
  fi
  if [ "$owned" -eq 1 ]; then
    /bin/rm -f -- "$cidfile" "$run_dir/executor.py" "$run_dir/database.env" \
      "$run_dir/operations.json" "$run_dir/storage.env" \
      "$run_dir/stdout" "$run_dir/stderr" 2>/dev/null || :
    /bin/rmdir "$run_dir" 2>/dev/null || :
  fi
}}
trap cleanup EXIT HUP INT TERM
[ -f "$unit" ] && [ ! -L "$unit" ]
[ "$(/usr/bin/sha256sum "$unit" | /usr/bin/awk '{{print $1}}')" = '{unit_sha}' ]
[ "$(/bin/systemctl show -p ActiveState --value "$(/usr/bin/basename "$unit")")" = inactive ]
[ "$(/bin/systemctl show -p UnitFileState --value "$(/usr/bin/basename "$unit")")" = disabled ]
for guarded in noteai-ai-{guarded_component} noteai-ai-{guarded_component}-acceptance; do
  rows=$(/usr/bin/docker container ls -a --filter "name=^/${{guarded}}$" --format '{{{{.ID}}}}')
  [ -z "$rows" ]
done
task_rows=$(/usr/bin/docker container ls -a --filter label=noteai.task=item29-capacity-100-v1 --format '{{{{.ID}}}}')
[ -z "$task_rows" ]
[ -f "$src_gz" ] && [ ! -L "$src_gz" ]
[ "$(/usr/bin/stat -c '%a:%u:%g:%h' "$src_gz")" = '400:0:0:1' ]
[ "$(/usr/bin/sha256sum "$src_gz" | /usr/bin/awk '{{print $1}}')" = '{source_gz_sha}' ]
[ "$(/usr/bin/docker image inspect -f '{{{{.Id}}}}' '{IMAGE}')" = '{IMAGE_CONFIG}' ]
[ "$(/usr/bin/docker image inspect -f '{{{{.Os}}}}' '{IMAGE}')" = 'linux' ]
[ "$(/usr/bin/docker image inspect -f '{{{{.Architecture}}}}' '{IMAGE}')" = 'amd64' ]
[ "$(/usr/bin/docker image inspect -f '{{{{.Config.User}}}}' '{IMAGE}')" = 'noteai' ]
[ "$(/usr/bin/docker image inspect -f '{{{{json .Config.Entrypoint}}}}' '{IMAGE}')" = '["/app/scripts/docker_entrypoint.sh"]' ]
[ "$(/usr/bin/docker image inspect -f '{{{{json .Config.Cmd}}}}' '{IMAGE}')" = '["python","durable_ai_worker.py","--once"]' ]
[ "$(/usr/bin/docker image inspect -f '{{{{ index .Config.Labels "org.opencontainers.image.revision" }}}}' '{IMAGE}')" = '{C17_REVISION}' ]
[ "$(/usr/bin/docker image inspect -f '{{{{ index .Config.Labels "com.noteai.runtime.role" }}}}' '{IMAGE}')" = 'ai-worker' ]
[ "$(/usr/bin/docker image inspect -f '{{{{len .RepoDigests}}}}' '{IMAGE}')" = '1' ]
[ "$(/usr/bin/docker image inspect -f '{{{{range .RepoDigests}}}}{{{{println .}}}}{{{{end}}}}' '{IMAGE}' | /bin/grep -Fxc '{IMAGE}')" = '1' ]
/bin/mkdir -m 0700 "$run_dir"; owned=1
! /usr/bin/docker inspect "$container" >/dev/null 2>&1
src=$run_dir/executor.py; db_env=$run_dir/database.env; ops=$run_dir/operations.json
storage_env=$run_dir/storage.env; out=$run_dir/stdout; err=$run_dir/stderr
(set -C; : >"$src"; : >"$db_env"; : >"$ops"; : >"$storage_env"; : >"$out"; : >"$err")
/usr/bin/gzip -dc "$src_gz" >"$src"
[ "$(/usr/bin/sha256sum "$src" | /usr/bin/awk '{{print $1}}')" = '{EXECUTOR_SHA256}' ]
[ -f '{env_source}' ] && [ ! -L '{env_source}' ]
[ "$(/usr/bin/stat -c '%a:%u:%g:%h' '{env_source}')" = '600:0:0:1' ]
[ "$(/bin/grep -c '^DATABASE_URL=' '{env_source}')" -eq 1 ]
/bin/grep '^DATABASE_URL=' '{env_source}' >"$db_env"
! /bin/grep -Eq '^(ANTHROPIC_API_KEY|MOONSHOT_API_KEY|KIMI_API_KEY|CLAUDE_API_KEY)=' "$db_env"
{storage_setup}
printf '%s' '{operations_encoded}' | /usr/bin/base64 -d | /usr/bin/gzip -dc >"$ops"
chmod 0444 "$src" "$ops"; chmod 0400 "$db_env"
dep=$(printf '%s' '{dependency_encoded}' | /usr/bin/base64 -d)
set +e
/usr/bin/docker run --rm --name "$container" --cidfile "$cidfile" \
  --label noteai.task=item29-capacity-100-v1 --label noteai.invocation="$invocation" \
  --pull=never --user=999:999 --read-only --cap-drop=ALL --security-opt=no-new-privileges:true \
  --network=bridge --ipc=private --memory=1536m --memory-swap=1536m --cpus=2 --pids-limit=256 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --env-file "$db_env" {storage_option} \
  -e PYTHONDONTWRITEBYTECODE=1 -e NOTEAI_DURABLE_AI_SUSPENDED=0 \
  -e NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1 \
  -e NOTEAI_DEPLOYMENT_STAGE=production -e NOTEAI_CLOUD_RUNTIME=1 \
  -e NOTEAI_ITEM29_ACCEPTANCE_MODE=production -e NOTEAI_ITEM29_MUTATION_CONFIRM='{mutation}' \
  -e NOTEAI_ITEM29_HOST_LABEL='{host_label}' \
  -e NOTEAI_DURABLE_AI_COMPONENT='{component}' -e NOTEAI_RUNTIME_ROLE='{runtime_role}' \
  -v "$src":/run/item29.py:ro -v "$ops":/run/operations.json:ro \
  --entrypoint=python '{IMAGE}' -I -B /run/item29.py \
  --phase '{inner_phase}' --plan-nonce '{value['plan_nonce']}' \
  --item28-dependency-json "$dep" --operations-json "$(/bin/cat "$ops")" {worker_option} \
  >"$out" 2>"$err"
rc=$?
set -e
out_b64=$(/usr/bin/base64 <"$out" | /usr/bin/tr -d '\n')
err_b64=$(/usr/bin/base64 <"$err" | /usr/bin/tr -d '\n')
cleanup
post_rc=0
[ ! -e "$run_dir" ] || post_rc=90
[ "$(/usr/bin/sha256sum "$unit" 2>/dev/null | /usr/bin/awk '{{print $1}}')" = '{unit_sha}' ] || post_rc=92
[ "$(/bin/systemctl show -p ActiveState --value "$(/usr/bin/basename "$unit")" 2>/dev/null)" = inactive ] || post_rc=93
[ "$(/bin/systemctl show -p UnitFileState --value "$(/usr/bin/basename "$unit")" 2>/dev/null)" = disabled ] || post_rc=94
! /usr/bin/docker inspect "$container" >/dev/null 2>&1 || post_rc=95
task_rows=$(/usr/bin/docker container ls -a --filter label=noteai.task=item29-capacity-100-v1 --format '{{{{.ID}}}}' 2>/dev/null || printf unknown)
[ -z "$task_rows" ] || post_rc=96
trap - EXIT HUP INT TERM
printf '%s' "$out_b64" | /usr/bin/base64 -d
printf '%s' "$err_b64" | /usr/bin/base64 -d >&2
if [ "$post_rc" -ne 0 ]; then printf 'item29_wrapper_postcheck=FAIL code=%s\n' "$post_rc" >&2; fi
[ "$rc" -ne 0 ] && exit "$rc"
exit "$post_rc"
""".encode("ascii")
    if len(wrapper) > MAX_COMMAND_CONTENT_BYTES:
        raise RequestError("command_too_large")
    return wrapper


def render_request(value, root=ROOT):
    action, operations = validate_input(value)
    kind, target, _inner, _worker = ACTION_SPECS[action]
    executor = read_executor(root)
    if kind == "send":
        compressed = _gzip(executor)
        request = {
            "Content": base64.b64encode(compressed).decode("ascii"),
            "ContentType": "Base64",
            "Description": "noteai-item29-capacity-100-write-once",
            "FileGroup": "root",
            "FileMode": "0400",
            "FileOwner": "root",
            "InstanceId": [target],
            "Name": SOURCE_NAME,
            "Overwrite": False,
            "RegionId": REGION,
            "Tag": [dict(TASK_TAG)],
            "TargetDir": "/run",
        }
        if set(request) != SEND_FILE_KEYS:
            raise RequestError("send_file_schema")
        return request, {
            "action": action,
            "api": "SendFile",
            "target": target,
            "executor_sha256": EXECUTOR_SHA256,
            "content_sha256": _sha(compressed),
            "overwrite": False,
            "same_request_resubmit_allowed": False,
        }
    if kind == "source-cleanup":
        wrapper = render_source_cleanup(executor, value)
    else:
        wrapper = render_wrapper(executor, value, operations)
    request = {
        "ClientToken": derive_client_token(value),
        "CommandContent": base64.b64encode(wrapper).decode("ascii"),
        "ContentEncoding": "Base64",
        "EnableParameter": False,
        "InstanceId": [target],
        "KeepCommand": True,
        "Name": f"noteai-item29-{action}-20260824-v1",
        "RegionId": REGION,
        "RepeatMode": "Once",
        "Tag": [dict(TASK_TAG)],
        "TerminationMode": "ProcessTree",
        "Timeout": 1800,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    if set(request) != RUN_COMMAND_KEYS:
        raise RequestError("run_command_schema")
    retry_safe = (
        kind == "source-cleanup"
        or action in {"admit-retry", "cleanup-retry"}
    )
    return request, {
        "action": action,
        "api": "RunCommand",
        "target": target,
        "executor_sha256": EXECUTOR_SHA256,
        "command_content_bytes": len(wrapper),
        "automatic_retry_allowed": retry_safe,
        "same_request_resubmit_allowed": retry_safe,
        "database_url_extracted_only": kind == "run",
        "real_provider_credentials_forwarded": False,
        "fixed_image": IMAGE if kind == "run" else None,
    }


def main(argv=None):
    del argv
    try:
        value = parse_canonical(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
        request, _validation = render_request(value)
    except RequestError as exc:
        sys.stderr.write(exc.code + "\n")
        return 3
    sys.stdout.buffer.write(canonical(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
