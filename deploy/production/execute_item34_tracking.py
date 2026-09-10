#!/usr/bin/env python3
"""Production adapter for the two bounded Item34 Tracking checkpoints.

The host-side command orchestrates short-lived, hardened containers. Database
reads and the two narrowly scoped writes execute inside the current immutable
XHS image, so this file never opens or copies an env file. The supplier worker
is always the existing exact command ``python crawler_worker.py --once --limit
1``. A provider-bearing container has a fixed stage name and is never started
twice; an uncertain start is stopped and left for read-only reconciliation.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / "tools"
if TOOLS.is_dir() and str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
MODEL = ROOT / "model"
if MODEL.is_dir() and str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

import execute_item34_tracking_checkpoint as checkpoint
from security_redaction import sanitize_xhs_http_event


IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STAGES = {"24h", "3d"}
INNER_ACTIONS = {"_snapshot", "_config", "_config_snapshot", "_schedule", "_bind", "_role", "_safety"}
MAX_OUTPUT_BYTES = 512 * 1024
LOCK_PATH = Path("/run/lock/noteai-item34-tracking.lock")
XHS_ENV_PATH = Path("/etc/noteai/xhs-tracking.env")
APP_ENV_PATH = Path("/etc/noteai/api.env")
DATA_PATH = Path("/var/lib/noteai/data")
UNIT = "noteai-xhs-tracking.service"
ACTIVE_CONFIG = {"enabled": True}
IMAGE_SOURCE_LABELS = {
    "com.noteai.item34.source.crawler-sha256": (
        "/app/model/crawler.py",
        "266af3cfa530523d893dc3e561ba5cf12a3c35936fb9a2212e1e212bb3b2437e",
    ),
    "com.noteai.item34.source.crawler-worker-sha256": (
        "/app/model/crawler_worker.py",
        "76d201334f20f9e013e810d8ea478ebda339054d1bc239aee1f45f11e5d9615a",
    ),
    "com.noteai.item34.source.db-sha256": (
        "/app/model/db.py",
        "44aba4b708bb250941ccd97965aebff0b1371ff588560e00601a2d625904de42",
    ),
    "com.noteai.item34.source.spider-sha256": (
        "/app/model/spider_xhs_http.py",
        "642c159992636b54bc4c26ffe70ca27caf48d025c5b693a4308074f9f8628ff7",
    ),
    "com.noteai.item34.source.tracking-contract-sha256": (
        "/app/model/tracking_contract.py",
        "cc28e19d7d8b1daae45e61c1bf442af700e4b9f4d2723f1bffb6e32f14087ce4",
    ),
    "com.noteai.item34.source.entrypoint-sha256": (
        "/app/scripts/docker_entrypoint.sh",
        "db155b05492fce0cab11e4a7ab23b080eb9064bc1e79cdcfde03dc8938e2d977",
    ),
}
# The old image identity above stays sealed. Prospective generation execution
# uses the independently built source below plus exact host/checkpoint bytes.
PROSPECTIVE_IMAGE_SOURCE_LABELS = dict(IMAGE_SOURCE_LABELS)
PROSPECTIVE_IMAGE_SOURCE_LABELS.update({
    'com.noteai.item34.source.entrypoint-sha256':('/app/scripts/docker_entrypoint.sh','39ddd93385f5e6f13a0f97a4e5d22031977cabbb1380d31e93624e6db71c48f3'),
    'com.noteai.item34.source.crawler-sha256':('/app/model/crawler.py','56f955f7ded2a95b942cf88061a6cf13052925e8b0fc4e02c639d540b53041a7'),
    'com.noteai.item34.source.db-sha256':('/app/model/db.py','818a134d966fe6e0dc0bfd4fda91bb1626380dc58e6ecec6bc426cddd04af93d'),
    'com.noteai.item34.source.tracking-contract-sha256':('/app/model/tracking_contract.py','8ce74c612e0ed2ce1bb886bf94d8d19087d87aef5fea0db529baccac303e2fc8'),
    'com.noteai.item34.source.observation-migration-sha256':('/app/model/migrations/postgres/0020_tracking_observation_generation.sql','22ef0a2c21529fe4d8ed38c42c2283ae61e6e6822d6411bd07620d353042d7a9'),
})

# Generation2 uses the repaired read path; prior image identities stay sealed.
RECOVERY_IMAGE_SOURCE_LABELS = dict(PROSPECTIVE_IMAGE_SOURCE_LABELS)
RECOVERY_IMAGE_SOURCE_LABELS.update({
    'com.noteai.item34.source.crawler-sha256':('/app/model/crawler.py','cd7d1dc738529a81101e90d14c2e32791c7067f3e89b5a0eab2a39875da6e0fa'),
    'com.noteai.item34.source.tracking-contract-sha256':('/app/model/tracking_contract.py','172ef39b85cfe5ae228d9aa4fdf6ec10a2269f0a816605f60dc577098dcd1a3e'),
    'com.noteai.item34.source.spider-sha256':('/app/model/spider_xhs_http.py','6ddcbfba6fbbb150744617eae63a3c0ceae50c2c4f7c8229bb81137f45af55f9'),
    'com.noteai.item34.source.v5-reader-sha256':('/app/model/spider_xhs_v5.py','36417a7ed30926c3243b422313ef4ea264cbd2550da62b5af963598a9f326047'),
    'com.noteai.item34.source.v5-runtime-sha256':('/app/model/vendor/spider_xhs/v5/runtime.py','45bb816e6205be506a0af4e9141507927c4a7bf3c1632aeedbe0ae6a139569dc'),
    'com.noteai.item34.source.v5-bridge-sha256':('/app/model/vendor/spider_xhs/v5/bridge.js','6f2989c286d6e1f0c3b2d0422c6a66c37938a99026593d5c006d751d0e653e7b'),
    'com.noteai.item34.source.v5-headers-sha256':('/app/model/vendor/spider_xhs/v5/headers.py','1f277bbc30af5b1b6d0dd0f44549dc97b95ac01a956f9dbb3d8f1a6b2db22356'),
    'com.noteai.item34.source.v5-manifest-sha256':('/app/model/vendor/spider_xhs/v5/upstream.json','ede5937cf326c3fe19edbae8e98cecc8dd9b3b5b983a87594f8d262336328fb6'),
    'com.noteai.item34.source.redaction-sha256':('/app/model/security_redaction.py','c5fc02966035a01012a1a35b7005f3a62a72602c042e98dbad707029ca56f451'),
})


def _worker_name(stage: str) -> str:
    binding=checkpoint.current_observation()
    generation=f"g{binding['generation']}-" if binding is not None else ""
    return f"noteai-item34-tracking-{generation}{stage}"


def _observation_file(path: Path) -> dict:
    _regular_root_file(path,"observation_file")
    if path.stat().st_size > 8192:
        _fail("observation_file")
    try:
        value=json.loads(path.read_bytes())
        with checkpoint.observation_context(value) as binding:
            if binding is None:_fail("observation_binding")
            return binding
    except (ValueError,UnicodeDecodeError):
        _fail("observation_file")


def _observation_environment() -> dict | None:
    raw=os.environ.get("NOTEAI_ITEM34_OBSERVATION_BINDING_B64","")
    if not raw:
        if os.environ.get('NOTEAI_ITEM34_OBSERVATION_GENERATION'):_fail('observation_environment')
        return None
    if len(raw)>12000:_fail("observation_environment")
    try:
        value=json.loads(base64.b64decode(raw,validate=True))
        with checkpoint.observation_context(value) as binding:
            if binding is None:_fail("observation_binding")
            return binding
    except (ValueError,UnicodeDecodeError):
        _fail("observation_environment")


def _observation_target(target: Mapping[str, Any], track_id: str) -> None:
    binding=checkpoint.current_observation()
    if binding is None:return
    if (track_id!=binding['track_id'] or str(target.get('id'))!=track_id
        or str(target.get('user_id'))!=binding['owner_id']
        or target.get('observation_generation')!=binding['generation']
        or _clock_text(target.get('observation_started_at'))!=checkpoint.window_clock('anchor')
        or target.get('observation_initial_snapshot')!=binding['initial_snapshot']):
        _fail('observation_row_binding')


def _history_projection(row: Mapping[str, Any]) -> dict:
    fields=('id','track_id','user_id','run_id','stage','status','admitted_at','completed_at','error_code')
    result={key:row[key] for key in fields}
    for key in ('admitted_at','completed_at'):
        result[key]=checkpoint._clock(str(result[key]),'observation_history').isoformat()
    result['observation_generation']=row.get('observation_generation',0)
    return result


def _observation_attempts(rows: list, track_id: str) -> list:
    binding=checkpoint.current_observation()
    if binding is None:return rows
    if track_id!=binding['track_id']:_fail('observation_history')
    try:
        return checkpoint.tracking_contract.assert_observation_history(rows,binding)
    except checkpoint.tracking_contract.TrackingContractError:
        _fail('observation_history')


SESSION_BLOCK_ERROR_CODES = {
    "challenge",
    "cooldown",
    "login_required",
    "login_or_challenge_required",
    "server_session_logged_out",
}
SESSION_BLOCK_TERMINAL_CODES = {
    "challenge": "xhs_session_blocked_challenge",
    "cooldown": "xhs_session_blocked_cooldown",
    "login_required": "xhs_session_blocked_login_required",
    "login_or_challenge_required": "xhs_session_blocked_login_or_challenge_required",
    "server_session_logged_out": "xhs_session_blocked_logged_out",
}


class ProductionAdapterError(RuntimeError):
    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise ProductionAdapterError(code)


def _canonical_uuid(value: Any, code: str = "identity") -> str:
    if not isinstance(value, str) or value != value.strip():
        _fail(code)
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, TypeError):
        _fail(code)
    if parsed != value:
        _fail(code)
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _attempt_digest(attempt_id: Any) -> str:
    canonical = _canonical_uuid(attempt_id, "attempt_identity")
    return _sha256(
        f"noteai-item34-tracking-attempt-row-v1:{canonical}".encode("ascii")
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_line(raw: bytes, code: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        _fail(code)
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        _fail(code)
    try:
        value = json.loads(lines[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    return value


def _worker_json_result(raw: bytes, http_observations: list | None = None) -> dict[str, Any]:
    """Parse bounded crawler event objects followed by one worker result."""
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        _fail("worker_json")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("worker_json")
    decoder = json.JSONDecoder()
    values: list[Any] = []
    position = 0
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        if len(values) >= 14:  # Existing seven crawler events + six HTTP events + result.
            _fail("worker_json")
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            _fail("worker_json")
        values.append(value)
    expected_keys = {
        "claimed",
        "attempted",
        "collected",
        "failed",
        "released",
        "total",
    }
    if not values or not isinstance(values[-1], dict):
        _fail("worker_json")
    observed, crawler_count, pending, sent = [], 0, None, 0
    for value in values[:-1]:
        if isinstance(value, dict) and set(value) == {"xhs_http"}:
            event = sanitize_xhs_http_event(value["xhs_http"])
            if not event or event != value["xhs_http"]:
                _fail("worker_json")
            if event["phase"] == "dispatch":
                if pending is not None or sent >= 3 or event["sequence"] != sent + 1:
                    _fail("worker_json")
                if event["request_kind"] != ("dsl", "session", "detail")[sent]:
                    _fail("worker_json")
                sent += 1
                pending = (event["sequence"], event["request_kind"])
            else:
                if pending != (event["sequence"], event["request_kind"]):
                    _fail("worker_json")
                pending = None
            observed.append(event)
            continue
        crawler_count += 1
        if (
            not isinstance(value, dict)
            or set(value) != {"crawler_event"}
            or not isinstance(value["crawler_event"], dict)
            or crawler_count > 7
        ):
            _fail("worker_json")
    if http_observations is not None:
        http_observations.extend(observed)
    result = values[-1]
    if set(result) == expected_keys:
        return result
    known_skip_reasons = {
        "server_session_logged_out",
        "collection_suspended",
        "collection_safety_unavailable",
        "runtime_role_not_allowed",
        "adapter_not_selected",
    }
    if (
        set(result) == {"skipped", "reason", "collected"}
        and result.get("skipped") is True
        and result.get("reason") in known_skip_reasons
        and result.get("collected") == 0
    ) or result == {"message": "暂无待采集记录", "collected": 0}:
        return {
            "claimed": 0,
            "attempted": 0,
            "collected": 0,
            "failed": 0,
            "released": 0,
            "total": 0,
        }
    _fail("worker_json")


def _run(
    argv: list[str],
    *,
    timeout: int,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("local_command_unknown")


def _regular_root_file(path: Path, code: str) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        _fail(code)
    if (
        not path.is_file()
        or path.is_symlink()
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o077
    ):
        _fail(code)


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        _fail("concurrent_execution")
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def _docker_json(argv: list[str], code: str) -> Any:
    completed = _run(argv, timeout=20)
    if completed.returncode != 0:
        _fail(code)
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)


def _expected_image_source_labels() -> dict[str, str]:
    binding=checkpoint.current_observation()
    sources=(RECOVERY_IMAGE_SOURCE_LABELS if binding and binding['generation']==2 else
             PROSPECTIVE_IMAGE_SOURCE_LABELS if binding is not None else IMAGE_SOURCE_LABELS)
    labels = {
        key: expected for key, (_path, expected) in sources.items()
    }
    labels["com.noteai.item34.source.wrapper-sha256"] = _sha256(
        Path(__file__).read_bytes()
    )
    labels["com.noteai.item34.source.checkpoint-sha256"] = _sha256(
        Path(checkpoint.__file__).read_bytes()
    )
    if binding and binding['generation']==2:
        for key, path in (('tracking-contract',Path(checkpoint.tracking_contract.__file__)),
                          ('redaction',MODEL/'security_redaction.py')):
            if _sha256(path.read_bytes())!=sources[f'com.noteai.item34.source.{key}-sha256'][1]:
                _fail('host_dependency_source_changed')
    return labels


def _image_preflight(image: str) -> str:
    if IMAGE_RE.fullmatch(image) is None:
        _fail("immutable_image")
    inspected = _docker_json(["docker", "image", "inspect", image], "image_readback")
    if not isinstance(inspected, list) or len(inspected) != 1:
        _fail("image_readback")
    item = inspected[0]
    config = item.get("Config") if isinstance(item, dict) else None
    labels = config.get("Labels") if isinstance(config, dict) else None
    expected_labels = _expected_image_source_labels()
    if (
        not isinstance(config, dict)
        or not isinstance(labels, dict)
        or labels.get("com.noteai.runtime.role") != "xhs-http"
        or config.get("Entrypoint") != ["/app/scripts/docker_entrypoint.sh"]
        or any(labels.get(key) != value for key, value in expected_labels.items())
        or image not in (item.get("RepoDigests") or [])
    ):
        _fail("image_contract")
    image_id = item.get("Id")
    if not isinstance(image_id, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", image_id
    ):
        _fail("image_contract")
    return image_id.removeprefix("sha256:")


def _service_state() -> dict[str, Any]:
    completed = _run(
        [
            "systemctl",
            "show",
            UNIT,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "UnitFileState",
        ],
        timeout=15,
    )
    if completed.returncode != 0:
        _fail("unit_readback")
    values = {}
    for line in completed.stdout.decode("utf-8", "strict").splitlines():
        if "=" not in line:
            _fail("unit_readback")
        key, value = line.split("=", 1)
        values[key] = value
    if set(values) != {"ActiveState", "SubState", "UnitFileState"}:
        _fail("unit_readback")
    active = values["ActiveState"]
    sub = values["SubState"]
    enabled = values["UnitFileState"]
    if (active, sub, enabled) != ("inactive", "dead", "disabled"):
        _fail("managed_unit_not_quiescent")
    running = _run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.noteai.item34=tracking-checkpoint",
        ],
        timeout=15,
    )
    if running.returncode != 0 or running.stdout.strip():
        _fail("task_runtime_not_quiescent")
    return {
        "unit_active_state": active,
        "unit_sub_state": sub,
        "unit_file_state": enabled,
        "task_container_count": 0,
    }


# Docker projects only these non-secret fields; never fetch complete Config.Env.
_CONTAINER_STATE_FORMAT = '[{"State":{"Running":{{json .State.Running}},"ExitCode":{{json .State.ExitCode}}}}]'
_OBSERVATION_ENV_KEYS = (
    'NOTEAI_ITEM34_ACCEPTANCE','NOTEAI_ITEM34_TRACK_ID','NOTEAI_ITEM34_CHECKPOINT_STAGE',
    'NOTEAI_ITEM34_OBSERVATION_GENERATION','NOTEAI_ITEM34_OBSERVATION_BINDING_B64',
    'NOTEAI_RUNTIME_ROLE','NOTEAI_XHS_SERVICE','NOTEAI_XHS_ACQUISITION_ADAPTER',
    'NOTEAI_XHS_PROTOCOL',
)
_OBSERVATION_CONTAINER_FORMAT = (
    '[{"Id":{{json .Id}},"Config":{"Image":{{json .Config.Image}},'
    '"Cmd":{{json .Config.Cmd}},"Entrypoint":{{json .Config.Entrypoint}},'
    '"Labels":{"com.noteai.item34.observation-binding-sha256":'
    '{{json (index .Config.Labels "com.noteai.item34.observation-binding-sha256")}}},'
    '"Env":[null{{range .Config.Env}}{{if or '+
    ' '.join('(eq (index (split . "=") 0) "'+key+'")' for key in _OBSERVATION_ENV_KEYS)+
    '}},{{json .}}{{end}}{{end}}]}}]'
)


def _observation_worker_environment(name: str) -> list[str]:
    binding=checkpoint.current_observation()
    stages=[stage for stage in STAGES if name==_worker_name(stage)]
    if binding is None or len(stages)!=1:_fail('observation_stop_binding')
    values=('1',binding['track_id'],stages[0],str(binding['generation']),
            base64.b64encode(_canonical_json(binding)).decode('ascii'),
            'xhs-http','tracking','spider_xhs_http')
    if binding['generation']==2:values+=('pc_v5',)
    return sorted(key+'='+value for key,value in zip(_OBSERVATION_ENV_KEYS,values))


def _container_exists(name: str) -> bool:
    completed = _run(["docker", "container", "inspect", "--format", "{{.Id}}", name], timeout=15)
    return completed.returncode == 0


def _stop_container(name: str) -> None:
    completed = _run(
        ["docker", "container", "stop", "--time", "10", name],
        timeout=20,
    )
    if completed.returncode != 0:
        _fail("container_stop")


def _remove_container(name: str) -> None:
    completed = _run(["docker", "container", "rm", name], timeout=20)
    if completed.returncode != 0:
        _fail("container_cleanup")


def _named_container_state(name: str) -> dict[str, Any] | None:
    listed = _run(
        [
            "docker",
            "container",
            "ls",
            "-a",
            "--filter",
            f"name=^/{name}$",
            "--format",
            "{{.Names}}",
        ],
        timeout=15,
    )
    if listed.returncode != 0:
        _fail("container_readback")
    names = [line for line in listed.stdout.decode("utf-8", "strict").splitlines() if line]
    if not names:
        return None
    if names != [name]:
        _fail("container_readback")
    inspected = _docker_json(
        ["docker", "container", "inspect", "--format", _CONTAINER_STATE_FORMAT, name],
        "container_readback",
    )
    state = (
        inspected[0].get("State", {})
        if isinstance(inspected, list) and len(inspected) == 1
        else None
    )
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("Running"), bool)
        or isinstance(state.get("ExitCode"), bool)
        or not isinstance(state.get("ExitCode"), int)
    ):
        _fail("container_readback")
    return {
        "running": state["Running"],
        "exit_code": int(state["ExitCode"]),
    }


def _quiesce_named_container(name: str, *, expected_image: str | None = None) -> dict[str, Any]:
    before = _named_container_state(name)
    container_id=None
    if checkpoint.current_observation() is not None and name.startswith('noteai-item34-tracking-'):
        if expected_image is None or IMAGE_RE.fullmatch(expected_image) is None:
            _fail('observation_stop_binding')
        if before is not None:
            items=_docker_json(['docker','container','inspect','--format',_OBSERVATION_CONTAINER_FORMAT,name],'container_readback')
            item=items[0] if isinstance(items,list) and len(items)==1 else {}
            config=item.get('Config',{})
            container_id=item.get('Id')
            if (not isinstance(container_id,str) or re.fullmatch(r'[0-9a-f]{64}',container_id) is None
                or config.get('Image')!=expected_image or config.get('Cmd')!=list(checkpoint.WORKER_ARGV)
                or config.get('Entrypoint')!=['/app/scripts/docker_entrypoint.sh']
                or not isinstance(config.get('Env'),list)
                or any(not isinstance(v,str) for v in config['Env'] if v is not None)
                or sorted(v for v in config['Env'] if v is not None)!=_observation_worker_environment(name)
                or config.get('Labels',{}).get('com.noteai.item34.observation-binding-sha256')!=
                   checkpoint.observation_identity()['observation_binding_sha256']):
                _fail('observation_container_identity')
    if before is not None and before["running"] is True:
        _stop_container(container_id or name)
    after = _named_container_state(name)
    if container_id is not None and after is not None:
        items=_docker_json(['docker','container','inspect','--format',_OBSERVATION_CONTAINER_FORMAT,name],'container_readback')
        if not isinstance(items,list) or len(items)!=1 or items[0].get('Id')!=container_id:
            _fail('observation_container_replaced')
    if after is not None and after["running"] is not False:
        _fail("container_not_quiescent")
    return {
        "container_identity_sha256": _sha256(
            f"noteai-item34-container-v1:{name}".encode("ascii")
        ),
        "container_present": after is not None,
        "before_running": before["running"] if before is not None else None,
        "before_exit_code": before["exit_code"] if before is not None else None,
        "after_running": after["running"] if after is not None else False,
        "after_exit_code": after["exit_code"] if after is not None else None,
        **({'container_id':container_id} if container_id is not None else {}),
    }


def _quiesce_worker(name: str, image: str | None) -> dict[str, Any]:
    if checkpoint.current_observation() is not None:
        return _quiesce_named_container(name,expected_image=image)
    return _quiesce_named_container(name)


def _cleanup_helper_container(name: str) -> None:
    try:
        state = _quiesce_named_container(name)
        if state["container_present"]:
            _remove_container(name)
        if _named_container_state(name) is not None:
            _fail("helper_container_unknown")
    except Exception:
        _fail("helper_container_unknown")


def _container_create_argv(
    *,
    name: str,
    image: str,
    env_file: Path,
    command: list[str],
    acceptance_track_id: str | None = None,
    acceptance_stage: str | None = None,
) -> list[str]:
    argv = [
        "docker",
        "container",
        "create",
        "--name",
        name,
        "--label",
        "com.noteai.item34=tracking-checkpoint",
        "--log-driver=local",
        "--log-opt=max-size=10m",
        "--log-opt=max-file=2",
        "--pull=never",
        "--user=999:999",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--network=bridge",
        "--ipc=private",
        "--memory=256m",
        "--cpus=0.25",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999",
        f"--mount=type=bind,src={DATA_PATH},dst=/app/model/data",
        f"--env-file={env_file}",
        "--env=NOTEAI_RUNTIME_ROLE=xhs-http",
        "--env=NOTEAI_DEPLOYMENT_STAGE=production",
        "--env=NOTEAI_CLOUD_RUNTIME=1",
        "--env=NOTEAI_XHS_SERVICE=tracking",
        "--env=NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1",
        "--env=NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http",
        "--env=NOTEAI_XHS_COLLECTION_SUSPENDED=0",
    ]
    if acceptance_track_id is not None or acceptance_stage is not None:
        if tuple(command) != checkpoint.WORKER_ARGV:
            _fail("acceptance_target_command")
        if acceptance_stage not in STAGES:
            _fail("acceptance_target_stage")
        target_id = _canonical_uuid(
            str(acceptance_track_id or ""),
            "acceptance_target_identity",
        )
        argv.extend(
            [
                "--env=NOTEAI_ITEM34_ACCEPTANCE=1",
                f"--env=NOTEAI_ITEM34_TRACK_ID={target_id}",
                f"--env=NOTEAI_ITEM34_CHECKPOINT_STAGE={acceptance_stage}",
            ]
        )
    binding=checkpoint.current_observation()
    if binding is not None:
        if acceptance_track_id is not None and binding['track_id']!=acceptance_track_id:
            _fail('observation_row_binding')
        argv.extend([
            '--label=com.noteai.item34.observation-binding-sha256='+checkpoint.observation_identity()['observation_binding_sha256'],
            '--env=NOTEAI_ITEM34_OBSERVATION_BINDING_B64='+base64.b64encode(_canonical_json(binding)).decode('ascii'),
            f"--env=NOTEAI_ITEM34_OBSERVATION_GENERATION={binding['generation']}",
        ])
        if binding['generation']==2:
            argv.append('--env=NOTEAI_XHS_PROTOCOL=pc_v5')
    return [*argv, image, *command]


def _start_known_container(
    name: str, *, timeout: int, provider: bool, image: str | None = None
) -> tuple[bytes, int]:
    try:
        completed = subprocess.run(
            ["docker", "container", "start", "--attach", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        try:
            _quiesce_worker(name,image) if provider else _quiesce_named_container(name)
        except Exception:
            _fail("worker_runtime_unknown" if provider else "container_result_unknown")
        _fail("worker_outcome_unknown" if provider else "container_result_unknown")
    inspected = _docker_json(
        ["docker", "container", "inspect", "--format", _CONTAINER_STATE_FORMAT, name], "container_readback"
    )
    state = (
        inspected[0].get("State", {})
        if isinstance(inspected, list) and len(inspected) == 1
        else None
    )
    if (
        not isinstance(state, dict)
        or state.get("Running") is not False
        or isinstance(state.get("ExitCode"), bool)
        or not isinstance(state.get("ExitCode"), int)
    ):
        if provider:
            try:
                _quiesce_worker(name,image)
            except Exception:
                _fail("worker_runtime_unknown")
        _fail("worker_outcome_unknown" if provider else "container_result")
    exit_code = int(state["ExitCode"])
    if not provider and (completed.returncode != 0 or exit_code != 0):
        _fail("container_result")
    return completed.stdout, exit_code


class HostAdapter:
    def __init__(self, *, image: str, stage: str, track_id: str):
        if stage not in STAGES:
            _fail("stage")
        self.image = image
        self.stage = stage
        self.track_id = _canonical_uuid(track_id, "track_identity")
        self.image_sha256 = _image_preflight(image)
        _regular_root_file(XHS_ENV_PATH, "xhs_env_file")
        _regular_root_file(APP_ENV_PATH, "app_env_file")
        if not DATA_PATH.is_dir():
            _fail("data_path")
        self.runtime_state = _service_state()
        self.initial_private: dict[str, Any] | None = None
        self.latest_private: dict[str, Any] | None = None
        self.last_worker: dict[str, Any] | None = None
        self.transition_used = False
        self.active_config_updated_at: str | None = None
        self.worker_name = _worker_name(stage)

    def _short_container(
        self,
        purpose: str,
        command: list[str],
        *,
        env_file: Path = APP_ENV_PATH,
    ) -> dict[str, Any]:
        name = f"noteai-item34-{purpose}-{uuid.uuid4().hex[:12]}"
        try:
            created = _run(
                _container_create_argv(
                    name=name,
                    image=self.image,
                    env_file=env_file,
                    command=command,
                ),
                timeout=30,
            )
            if created.returncode != 0:
                _fail("container_create")
            raw, _exit_code = _start_known_container(
                name, timeout=45, provider=False
            )
            return _json_line(raw, "container_json")
        finally:
            _cleanup_helper_container(name)

    def _role_readback(self) -> None:
        value = self._short_container(
            "role",
            ["python", "execute_item34_tracking.py", "_role", self.stage, self.track_id],
            env_file=XHS_ENV_PATH,
        )
        expected_keys = {
            "current_user",
            "visible_setting_keys",
            "visible_secret_rows",
            "visible_unapproved_setting_rows",
            "session_configured",
            "session_status",
            "session_cookie_count",
            "session_a1_present",
            "session_auth_cookie_present",
            "session_auth_cookie_expired",
            "signer_assets_verified",
            "signer_asset_count",
            "secret_values_recorded",
            "tracking_daily_provider_limit",
            "tracking_daily_provider_used",
            "tracking_daily_provider_remaining",
        }
        if not isinstance(value, dict) or set(value) != expected_keys:
            _fail("tracking_role_readback")
        visible = value.get("visible_setting_keys")
        daily_used = value.get("tracking_daily_provider_used")
        daily_remaining = value.get("tracking_daily_provider_remaining")
        if (
            value.get("current_user") != "noteai_xhs_tracking"
            or not isinstance(visible, list)
            or "crawler_config" not in visible
            or not set(visible).issubset(
                {"crawler_config", "xhs_collection_safety"}
            )
            or value.get("visible_secret_rows") != 0
            or value.get("visible_unapproved_setting_rows") != 0
            or value.get("session_configured") is not True
            or value.get("session_status") != "ready"
            or isinstance(value.get("session_cookie_count"), bool)
            or not isinstance(value.get("session_cookie_count"), int)
            or value["session_cookie_count"] < 2
            or value.get("session_a1_present") is not True
            or value.get("session_auth_cookie_present") is not True
            or value.get("session_auth_cookie_expired") is not False
            or value.get("signer_assets_verified") is not True
            or isinstance(value.get("signer_asset_count"), bool)
            or not isinstance(value.get("signer_asset_count"), int)
            or value["signer_asset_count"] < 1
            or value.get("secret_values_recorded") is not False
            or value.get("tracking_daily_provider_limit") != 300
            or isinstance(daily_used, bool)
            or not isinstance(daily_used, int)
            or daily_used < 0
            or isinstance(daily_remaining, bool)
            or not isinstance(daily_remaining, int)
            or daily_remaining != 300 - daily_used
            or daily_remaining < 1
        ):
            _fail("tracking_role_readback")

    def read_snapshot(self, *, phase: str) -> Mapping[str, Any]:
        value = self._short_container(
            f"snapshot-{phase}",
            [
                "python",
                "execute_item34_tracking.py",
                "_snapshot",
                self.stage,
                self.track_id,
            ],
        )
        if set(value) != {"snapshot", "private"}:
            _fail("snapshot_contract")
        snapshot = value["snapshot"]
        private = value["private"]
        if not isinstance(snapshot, dict) or not isinstance(private, dict):
            _fail("snapshot_contract")
        self.latest_private = private
        safety = private.get("safety")
        if not isinstance(safety, dict):
            _fail("collection_safety_readback")
        if phase != "failure" and safety.get("session_blocked") is True:
            _fail("collection_safety_blocked")
        snapshot = dict(snapshot)
        snapshot["runtime_state"] = dict(self.runtime_state)
        if self.initial_private is None:
            self.initial_private = private
        if phase == "post":
            if self.last_worker is None or self.initial_private is None:
                _fail("postflight_order")
            before = self.initial_private.get("audit")
            after = private.get("audit")
            if not isinstance(before, dict) or not isinstance(after, dict):
                _fail("write_audit")
            snapshot["run"] = dict(self.last_worker["run"])
            snapshot["write_audit"] = _write_audit(
                self.stage,
                before,
                after,
                transition_used=self.transition_used,
            )
            if self.stage == "3d":
                snapshot["terminal_effects"] = {
                    "growth_record_count": after.get("growth_record_count"),
                    "user_memory_count": after.get("user_memory_count"),
                    "training_eligible": snapshot["target"].get(
                        "training_eligible"
                    ),
                    "score_window": snapshot["target"].get("score_window"),
                    "growth_action": after.get("growth_action"),
                    "memory_window": after.get("memory_window"),
                    "memory_content_sha256": after.get(
                        "memory_content_sha256"
                    ),
                    "ledger_sha256": after.get("ledger_sha256"),
                }
        return snapshot

    def authorization(self) -> dict[str, Any] | None:
        if self.initial_private is None:
            _fail("preflight_order")
        config = self.initial_private.get("config")
        if not isinstance(config, dict):
            _fail("config_contract")
        if config.get("enabled") is True and config.get("suspended") is False:
            return None
        active_raw = _canonical_json(ACTIVE_CONFIG)
        self.transition_used = True
        self.active_config_updated_at = datetime.now(timezone.utc).isoformat()
        return {
            "schema": checkpoint.TRANSITION_SCHEMA,
            "transition_id": hashlib.sha256(
                _canonical_json(
                    {
                        "item": 34,
                        "stage": self.stage,
                        "track_id": self.track_id,
                        "image": self.image_sha256,
                        "original": config,
                    }
                )
            ).hexdigest(),
            "action": (
                "item34_single_24h_checkpoint"
                if self.stage == "24h"
                else "item34_single_3d_checkpoint"
            ),
            "restore_required": True,
            "worker_argv": list(checkpoint.WORKER_ARGV),
            "expected_original_config_present": config.get("present"),
            "expected_original_config_sha256": config.get("sha256"),
            "expected_active_config_sha256": _sha256(active_raw),
        }

    def transition(self, phase: str, authorization: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.initial_private is None or phase not in {"activate", "restore"}:
            _fail("transition")
        if self.active_config_updated_at is None:
            _fail("transition")
        config = self.initial_private["config"]
        environment = {
            "NOTEAI_ITEM34_TRANSITION_ID": str(authorization["transition_id"]),
            "NOTEAI_ITEM34_ORIGINAL_PRESENT": "1" if config["present"] else "0",
            "NOTEAI_ITEM34_ORIGINAL_SHA256": str(config["sha256"] or ""),
            "NOTEAI_ITEM34_ORIGINAL_B64": str(config["value_b64"] or ""),
            "NOTEAI_ITEM34_ORIGINAL_UPDATED_AT": str(
                config["updated_at"] or ""
            ),
            "NOTEAI_ITEM34_ACTIVE_B64": base64.b64encode(
                _canonical_json(ACTIVE_CONFIG)
            ).decode("ascii"),
            "NOTEAI_ITEM34_ACTIVE_UPDATED_AT": self.active_config_updated_at,
        }
        command = ["python", "execute_item34_tracking.py", "_config", phase, self.track_id]
        return self._short_container_with_env(f"config-{phase}", command, environment)

    def _short_container_with_env(
        self,
        purpose: str,
        command: list[str],
        environment: Mapping[str, str],
    ) -> dict[str, Any]:
        name = f"noteai-item34-{purpose}-{uuid.uuid4().hex[:12]}"
        argv = _container_create_argv(
            name=name,
            image=self.image,
            env_file=APP_ENV_PATH,
            command=command,
        )
        insert_at = argv.index(self.image)
        for key in sorted(environment):
            argv[insert_at:insert_at] = ["--env", f"{key}={environment[key]}"]
            insert_at += 2
        try:
            created = _run(argv, timeout=30)
            if created.returncode != 0:
                _fail("container_create")
            return _json_line(
                _start_known_container(name, timeout=45, provider=False)[0],
                "container_json",
            )
        finally:
            _cleanup_helper_container(name)

    def read_transition_state(self) -> Mapping[str, Any]:
        if checkpoint.current_observation() is not None:
            config=self.read_config_snapshot()['config']
            return {'crawler_enabled':config['enabled'],'collection_suspended':config['suspended'],
                'crawler_config_present':config['present'],'crawler_config_sha256':config['sha256'],
                'runtime_role':'xhs-http','adapter':'spider_xhs_http'}
        snapshot = self.read_snapshot(phase="transition")
        return snapshot["production_config"]

    def failure_readback(self) -> Mapping[str, Any]:
        self.read_snapshot(phase="failure")
        if self.latest_private is None:
            _fail("failure_readback")
        failure = self.latest_private.get("failure")
        if not isinstance(failure, dict):
            _fail("failure_readback")
        return failure

    def persist_session_block(self, failure: Mapping[str, Any]) -> Mapping[str, Any]:
        if (
            self.latest_private is None
            or failure.get("status") != "failed"
            or failure.get("error_code") not in SESSION_BLOCK_ERROR_CODES
        ):
            _fail("failure_readback")
        safety = self.latest_private.get("safety")
        if not isinstance(safety, dict):
            _fail("collection_safety_readback")
        environment = {
            "NOTEAI_ITEM34_SAFETY_EXPECTED_PRESENT": (
                "1" if safety.get("present") is True else "0"
            ),
            "NOTEAI_ITEM34_SAFETY_EXPECTED_SHA256": str(
                safety.get("sha256") or ""
            ),
            "NOTEAI_ITEM34_SAFETY_FAILURE_CODE": str(failure["error_code"]),
            "NOTEAI_ITEM34_SAFETY_BLOCKED_AT": datetime.now(
                timezone.utc
            ).isoformat(),
        }
        value = self._short_container_with_env(
            "safety-block",
            ["python", "execute_item34_tracking.py", "_safety", self.stage, self.track_id],
            environment,
        )
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "status",
            "track_identity_sha256",
            "reason_code",
            "failure_code",
            "state_sha256",
            "configuration_mutations",
            "provider_calls",
            "secret_values_recorded",
        }:
            _fail("safety_readback")
        mutations = value.get("configuration_mutations")
        if (
            value.get("schema") != "noteai.item34.collection_safety_block.v1"
            or value.get("status") not in {"BLOCKED", "ALREADY_BLOCKED"}
            or value.get("track_identity_sha256")
            != _sha256(
                f"noteai-item34-tracking-row-v1:{self.track_id}".encode("ascii")
            )
            or value.get("reason_code") != "server_session_logged_out"
            or value.get("failure_code") != failure["error_code"]
            or SHA256_RE.fullmatch(str(value.get("state_sha256") or "")) is None
            or isinstance(mutations, bool)
            or mutations not in {0, 1}
            or value.get("provider_calls") != 0
            or value.get("secret_values_recorded") is not False
        ):
            _fail("safety_readback")
        return value

    def schedule_3d(self, track_id: str, due_at: str) -> Mapping[str, Any]:
        if track_id != self.track_id or due_at != checkpoint.window_clock('3d'):
            _fail("schedule_binding")
        return self._short_container(
            "schedule",
            ["python", "execute_item34_tracking.py", "_schedule", "24h", track_id],
        )

    def bind_24h_schedule(self) -> Mapping[str, Any]:
        if self.stage != "24h":
            _fail("bind_stage")
        return self._short_container(
            "bind-24h",
            ["python", "execute_item34_tracking.py", "_bind", "24h", self.track_id],
        )

    def run_worker(self, argv: tuple[str, ...]) -> Mapping[str, Any]:
        if (
            tuple(argv) != checkpoint.WORKER_ARGV
            or _named_container_state(self.worker_name) is not None
        ):
            _fail("worker_container_requires_reconciliation")
        try:
            self._role_readback()
            created = _run(
                _container_create_argv(
                    name=self.worker_name,
                    image=self.image,
                    env_file=XHS_ENV_PATH,
                    command=list(argv),
                    acceptance_track_id=self.track_id,
                    acceptance_stage=self.stage,
                ),
                timeout=30,
            )
            if created.returncode != 0:
                _fail("worker_container_create")
        except ProductionAdapterError as exc:
            if exc.code in {
                "container_readback",
                "helper_container_unknown",
                "worker_container_requires_reconciliation",
            }:
                raise
            state = _quiesce_worker(self.worker_name,self.image)
            if state["container_present"]:
                _remove_container(state.get('container_id') or self.worker_name)
            result = {
                "claimed": 0,
                "attempted": 0,
                "collected": 0,
                "failed": 0,
                "released": 0,
                "total": 0,
            }
            self.last_worker = {
                "run": {
                    "run_id": "",
                    "worker_argv": list(argv),
                    "worker_invocation_count": 0,
                    "automatic_retry_count": 0,
                    "attempted": 0,
                    "collected": 0,
                    "failed": 0,
                },
                "result": result,
            }
            return {
                "exit_code": 1,
                "invocation_count": 0,
                "automatic_retry_count": 0,
                "result": result,
            }
        raw, exit_code = _start_known_container(
            self.worker_name, timeout=150, provider=True,
            **({'image':self.image} if checkpoint.current_observation() is not None else {})
        )
        http_observations: list = []
        result = _worker_json_result(raw, http_observations)
        self.last_worker = {
            "run": {
                "run_id": "",
                "worker_argv": list(argv),
                "worker_invocation_count": 1,
                "automatic_retry_count": 0,
                "attempted": result["attempted"],
                "collected": result["collected"],
                "failed": result["failed"],
            },
            "result": result,
            "http_observations": http_observations,
        }
        return {
            "exit_code": exit_code,
            "invocation_count": 1,
            "automatic_retry_count": 0,
            "result": result,
        }

    def finish_worker_readback(self, snapshot: Mapping[str, Any]) -> None:
        if self.last_worker is None:
            return
        rows = snapshot.get("attempts", {}).get("rows", [])
        current_stage = "24h" if self.stage == "24h" else "7d"
        matches = [row for row in rows if row.get("stage") == current_stage]
        if len(matches) != 1:
            _fail("worker_attempt_readback")
        self.last_worker["run"]["run_id"] = matches[0]["run_id"]

    def cleanup_known_worker(self) -> None:
        state = _quiesce_worker(self.worker_name,self.image)
        if state["container_present"]:
            _remove_container(state.get('container_id') or self.worker_name)

    def read_config_snapshot(self) -> dict:
        return self._short_container('config-readback',
            ['python','execute_item34_tracking.py','_config_snapshot',self.stage,self.track_id])


def _write_audit(
    stage: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    transition_used: bool,
) -> dict[str, int]:
    def delta(key: str) -> int:
        left, right = before.get(key), after.get(key)
        if isinstance(left, bool) or isinstance(right, bool):
            _fail("write_audit")
        if not isinstance(left, int) or not isinstance(right, int) or right < left:
            _fail("write_audit")
        return right - left

    expected = {
        "target_tracked_notes_distinct_rows": 1,
        "other_tracked_notes_row_mutations": 0,
        "tracking_provider_attempts_inserted": delta("attempt_count"),
        "crawler_events_inserted": delta("crawler_event_count"),
        "system_settings_row_mutations": 1 if transition_used else 0,
        "other_system_settings_row_mutations": 0,
        "out_of_contract_row_mutations": 0,
    }
    if stage == "3d":
        expected.update(
            {
                "growth_records_inserted": delta("growth_record_count"),
                "user_memories_inserted": delta("user_memory_count"),
            }
        )
    return expected


def _execute_host(stage: str, track_id: str, image: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        _fail("root_required")
    with _exclusive_lock(LOCK_PATH):
        adapter = HostAdapter(image=image, stage=stage, track_id=track_id)
        initial = adapter.read_snapshot(phase="pre")
        authorization = adapter.authorization()
        preflight_reads = 0

        def preflight() -> Mapping[str, Any]:
            nonlocal preflight_reads
            preflight_reads += 1
            if preflight_reads == 1:
                return initial
            return adapter.read_snapshot(phase="pre")

        def postflight() -> Mapping[str, Any]:
            snapshot = adapter.read_snapshot(phase="post")
            adapter.finish_worker_readback(snapshot)
            snapshot["run"] = dict(adapter.last_worker["run"])  # type: ignore[index]
            return snapshot

        kwargs = {
            "expected_track_id": track_id,
            "read_preflight": preflight,
            "run_worker": adapter.run_worker,
            "read_postflight": postflight,
            "clock": lambda: datetime.now(timezone.utc),
            "transition_authorization": authorization,
            "transition_config": adapter.transition if authorization else None,
            "read_transition_state": (
                adapter.read_transition_state if authorization else None
            ),
        }
        try:
            if stage == "24h":
                result = checkpoint.execute_24h_checkpoint(
                    **kwargs,
                    schedule_3d=adapter.schedule_3d,
                )
            else:
                result = checkpoint.execute_3d_checkpoint(**kwargs)
        except Exception:
            _quiesce_worker(adapter.worker_name,adapter.image)
            terminal_code: str | None = None
            if adapter.last_worker is not None:
                try:
                    if adapter.last_worker["result"].get("attempted") == 0:
                        adapter.cleanup_known_worker()
                    else:
                        failure = adapter.failure_readback()
                        if (
                            failure.get("status") == "failed"
                            and failure.get("error_code")
                            in SESSION_BLOCK_ERROR_CODES
                        ):
                            adapter.persist_session_block(failure)
                            adapter.cleanup_known_worker()
                            terminal_code = SESSION_BLOCK_TERMINAL_CODES[
                                str(failure["error_code"])
                            ]
                except Exception:
                    _fail("collection_safety_reconciliation_unknown")
            if terminal_code is not None:
                _fail(terminal_code)
            raise
        adapter.cleanup_known_worker()
        if _service_state() != adapter.runtime_state:
            _fail("final_runtime_state")
        result["immutable_artifact_sha256"] = adapter.image_sha256
        result["production_wrapper"] = "deploy/production/execute_item34_tracking.py"
        result["secret_values_recorded"] = False
        return result


def _connect(*, write: bool):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        _fail("database_driver")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        _fail("database_url")
    options = "-c timezone=UTC -c statement_timeout=15000"
    if not write:
        options += " -c default_transaction_read_only=on"
    try:
        return psycopg.connect(
            database_url,
            autocommit=False,
            connect_timeout=10,
            options=options,
            row_factory=dict_row,
        )
    except Exception:
        _fail("database_connect")


def _clock_text(value: Any) -> str | None:
    if value is None:
        return None
    if checkpoint.current_observation() is not None:
        raw=value.isoformat() if isinstance(value,datetime) else str(value)
        if re.match(r'^\d{4}-\d\d-\d\dT',raw):
            return checkpoint._clock(raw,'observation_clock').isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _collection_safety_projection(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {
            "present": False,
            "sha256": None,
            "session_blocked": False,
            "reason_code": "",
            "blocked_at": "",
        }
    if not isinstance(raw, str):
        _fail("collection_safety_readback")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        _fail("collection_safety_readback")
    if not isinstance(value, dict):
        _fail("collection_safety_readback")
    blocked = value.get("session_blocked") is True
    reason = str(value.get("reason_code") or "")
    blocked_at = str(value.get("blocked_at") or "")
    if blocked:
        if reason != "server_session_logged_out":
            _fail("collection_safety_readback")
        _transition_clock(blocked_at, required=True)
    elif reason or blocked_at:
        _fail("collection_safety_readback")
    return {
        "present": True,
        "sha256": _sha256(raw.encode("utf-8")),
        "session_blocked": blocked,
        "reason_code": reason if blocked else "",
        "blocked_at": blocked_at if blocked else "",
    }


def _inner_config_snapshot() -> dict[str, Any]:
    """Only the already-authorized non-secret CAS object, even if sampling is UNKNOWN."""
    connection=_connect(write=False)
    try:
        with connection.transaction(),connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute('SELECT current_user')
            if cursor.fetchone()['current_user']!='noteai_app':_fail('audit_role')
            cursor.execute("SELECT value_json,is_secret,updated_at FROM system_settings WHERE key='crawler_config'")
            rows=cursor.fetchall()
            if len(rows)>1 or (rows and rows[0]['is_secret']!=0):_fail('crawler_config')
            raw=rows[0]['value_json'] if rows else None
            try:value=json.loads(raw) if raw is not None else None
            except (TypeError,ValueError):_fail('crawler_config')
            if value is not None and not isinstance(value,dict):_fail('crawler_config')
            return {'config':{'present':bool(rows),'enabled':bool(value and value.get('enabled') is True),
                'suspended':False,'sha256':_sha256(raw.encode()) if rows else None,
                'value_b64':base64.b64encode(raw.encode()).decode() if rows else None,
                'updated_at':str(rows[0]['updated_at']) if rows else None}}
    finally:
        connection.close()


def _inner_snapshot(stage: str, track_id: str) -> dict[str, Any]:
    expected_attempt_stages = {"24h"} if stage == "3d" else set()
    connection = _connect(write=False)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SHOW transaction_read_only")
                if cursor.fetchone()["transaction_read_only"] != "on":
                    _fail("database_read_only")
                cursor.execute("SELECT current_user,clock_timestamp() AS observed_at")
                identity = cursor.fetchone()
                if identity["current_user"] != "noteai_app":
                    _fail("audit_role")
                observed = identity["observed_at"]
                cursor.execute(
                    "SELECT value_json,is_secret,updated_at FROM system_settings "
                    "WHERE key='crawler_config'"
                )
                config_rows = cursor.fetchall()
                if len(config_rows) > 1 or (
                    config_rows and config_rows[0]["is_secret"] != 0
                ):
                    _fail("crawler_config")
                config_raw = config_rows[0]["value_json"] if config_rows else None
                try:
                    config_value = json.loads(config_raw) if config_raw is not None else None
                except (TypeError, json.JSONDecodeError):
                    _fail("crawler_config")
                if config_value is not None and not isinstance(config_value, dict):
                    _fail("crawler_config")
                cursor.execute(
                    "SELECT value_json,is_secret FROM system_settings "
                    "WHERE key='xhs_collection_safety'"
                )
                safety_rows = cursor.fetchall()
                if len(safety_rows) > 1 or (
                    safety_rows and safety_rows[0]["is_secret"] != 0
                ):
                    _fail("collection_safety_readback")
                safety = _collection_safety_projection(
                    safety_rows[0]["value_json"] if safety_rows else None
                )
                cursor.execute(
                    "SELECT * FROM tracked_notes WHERE xhs_note_id=%s",
                    (checkpoint.CANONICAL_NOTE_ID,),
                )
                targets = cursor.fetchall()
                if len(targets) != 1:
                    _fail("managed_row_missing" if not targets else "managed_row_ambiguous")
                target = targets[0]
                if str(target["id"]) != track_id:
                    _fail("managed_row_binding")
                if target["xhs_url"] != checkpoint.CANONICAL_URL:
                    _fail("managed_row_binding")
                _observation_target(target,track_id)

                now_text = _clock_text(observed)
                h24 = _clock_text(observed.replace(tzinfo=timezone.utc))
                cursor.execute(
                    "SELECT id,xhs_note_id,status FROM tracked_notes WHERE "
                    "active_attempt_id IS NULL AND "
                    "(claim_token IS NULL OR claim_expires_at IS NULL OR "
                    "claim_expires_at::timestamptz<=%s::timestamptz) AND ("
                    "(status='pending' AND ((next_check_at IS NOT NULL AND "
                    "next_check_at::timestamptz<=%s::timestamptz) OR "
                    "(next_check_at IS NULL AND submitted_at::timestamptz"
                    "<=%s::timestamptz-interval '24 hours'))) OR "
                    "(status IN ('checking_7d','checking_24h') AND (("
                    "next_check_at IS NOT NULL AND next_check_at::timestamptz"
                    "<=%s::timestamptz) OR (next_check_at IS NULL AND "
                    "check_24h_at::timestamptz<=%s::timestamptz-interval '7 days')))) "
                    "ORDER BY COALESCE(next_check_at::timestamptz,submitted_at::timestamptz),"
                    "submitted_at::timestamptz,id",
                    (now_text, now_text, h24, now_text, now_text),
                )
                due_rows = cursor.fetchall()
                due = [
                    {
                        "track_id": str(row["id"]),
                        "note_id": str(row["xhs_note_id"]),
                        "stage": "24h" if row["status"] == "pending" else "7d",
                    }
                    for row in due_rows
                ]
                cursor.execute(
                    ("SELECT a.id,a.track_id,a.user_id,a.run_id,a.stage,a.status,a.admitted_at,"
                     "a.observation_generation," if checkpoint.current_observation() is not None else
                     "SELECT a.id,a.track_id,a.run_id,a.stage,a.status,a.admitted_at,")+
                    "a.completed_at,a.error_code,t.xhs_note_id FROM "
                    "tracking_provider_attempts a JOIN tracked_notes t ON "
                    "t.id=a.track_id AND t.user_id=a.user_id WHERE a.track_id=%s "
                    "ORDER BY CASE a.stage WHEN '24h' THEN 1 ELSE 2 END",
                    (track_id,),
                )
                attempts_raw = _observation_attempts(cursor.fetchall(),track_id)
                stages = {row["stage"] for row in attempts_raw}
                if not expected_attempt_stages.issubset(stages):
                    _fail("prior_attempt_missing")
                attempts = [
                    {
                        "track_id": str(row["track_id"]),
                        "note_id": str(row["xhs_note_id"]),
                        "stage": str(row["stage"]),
                        "status": str(row["status"]),
                        "run_id": str(row["run_id"]),
                        "attempt_id": str(row["id"]),
                        "admitted_at": _clock_text(row["admitted_at"]),
                        "completed_at": _clock_text(row["completed_at"]),
                    }
                    for row in attempts_raw
                ]
                cursor.execute(
                    "SELECT COUNT(*) FILTER (WHERE status='started') AS started,"
                    "COUNT(*) FILTER (WHERE status='failed' AND "
                    "error_code='provider_outcome_unknown') AS unknown FROM "
                    "tracking_provider_attempts"
                )
                global_attempts = cursor.fetchone()
                target_unknown = sum(
                    1
                    for row in attempts_raw
                    if row["status"] == "failed"
                    and row["error_code"] == "provider_outcome_unknown"
                )
                cursor.execute(
                    "SELECT id,user_id,xhs_note_id,status,next_check_at,check_24h_at,"
                    "check_7d_at,likes_24h,saves_24h,comments_24h,likes_7d,"
                    "saves_7d,comments_7d,claim_token,claim_expires_at,"
                    "active_attempt_id,last_checked_at,completed_at FROM tracked_notes "
                    "WHERE id<>%s ORDER BY id",
                    (track_id,),
                )
                non_target_rows = [dict(row) for row in cursor.fetchall()]
                for row in non_target_rows:
                    for key, value in list(row.items()):
                        row[key] = _clock_text(value)
                cursor.execute("SELECT COUNT(*) AS count FROM crawler_events")
                crawler_count = int(cursor.fetchone()["count"])
                import tracking_contract

                effect_growth = tracking_contract.deterministic_effect_id(
                    track_id, "growth", generation=(checkpoint.current_observation() or {}).get('generation',0)
                )
                effect_memory = tracking_contract.deterministic_effect_id(
                    track_id, "memory", generation=(checkpoint.current_observation() or {}).get('generation',0)
                )
                cursor.execute(
                    "SELECT action FROM growth_records WHERE id=%s",
                    (effect_growth,),
                )
                growth_rows = cursor.fetchall()
                if len(growth_rows) > 1:
                    _fail("terminal_effect_readback")
                growth_count = len(growth_rows)
                growth_raw = str(growth_rows[0]["action"]) if growth_rows else ""
                growth_action = (
                    growth_raw
                    if growth_raw in {"url_crawl_3d", "url_crawl_7d"}
                    else ("unrecognized" if growth_raw else "")
                )
                cursor.execute(
                    "SELECT content FROM user_memories WHERE id=%s",
                    (effect_memory,),
                )
                memory_rows = cursor.fetchall()
                if len(memory_rows) > 1:
                    _fail("terminal_effect_readback")
                memory_count = len(memory_rows)
                memory_content = memory_rows[0]["content"] if memory_rows else ""
                if not isinstance(memory_content, str):
                    _fail("terminal_effect_readback")
                memory_content_sha256 = (
                    _sha256(memory_content.encode("utf-8"))
                    if memory_content
                    else None
                )
                if "3天实际" in memory_content and "7天实际" not in memory_content:
                    memory_window = "3d"
                elif "7天实际" in memory_content and "3天实际" not in memory_content:
                    memory_window = "7d"
                else:
                    memory_window = "unrecognized" if memory_content else ""
    finally:
        connection.close()

    config_bytes = config_raw.encode("utf-8") if config_raw is not None else b""
    config_present = config_raw is not None
    config_enabled = bool(config_value and config_value.get("enabled") is True)
    training_raw = target["training_eligible"]
    if isinstance(training_raw, bool) or training_raw not in {0, 1}:
        _fail("terminal_effect_readback")
    score_window = None
    insights_raw = target["insights_json"]
    if insights_raw is not None:
        if not isinstance(insights_raw, str):
            _fail("terminal_effect_readback")
        try:
            insights = json.loads(insights_raw)
        except json.JSONDecodeError:
            _fail("terminal_effect_readback")
        if not isinstance(insights, dict) or not isinstance(
            insights.get("window"), str
        ):
            _fail("terminal_effect_readback")
        score_window = insights["window"]
    metrics = (
        {
            "likes": target["likes_24h"],
            "saves": target["saves_24h"],
            "comments": target["comments_24h"],
        }
        if stage == "24h" or target["status"] != "complete"
        else {
            "likes": target["likes_7d"],
            "saves": target["saves_7d"],
            "comments": target["comments_7d"],
        }
    )
    target_payload = {
        "track_id": track_id,
        "note_id": checkpoint.CANONICAL_NOTE_ID,
        "canonical_url": checkpoint.CANONICAL_URL,
        "object_identity_sha256": checkpoint.OBJECT_IDENTITY_SHA256,
        "status": target["status"],
        "next_check_at": _clock_text(target["next_check_at"]),
        "check_24h_at": _clock_text(target["check_24h_at"]),
        "check_7d_at": _clock_text(target["check_7d_at"]),
        "claim_present": bool(target["claim_token"] or target["claim_expires_at"]),
        "active_attempt_present": target["active_attempt_id"] is not None,
        "training_eligible": bool(training_raw),
        "score_window": score_window,
        "metrics": metrics,
    }
    attempt_count_24h = sum(row["stage"] == "24h" for row in attempts)
    attempt_count_7d = sum(row["stage"] == "7d" for row in attempts)
    ledger = {
        "target": target_payload,
        "attempts": attempts,
        "growth_record_count": growth_count,
        "user_memory_count": memory_count,
        "growth_action": growth_action,
        "memory_window": memory_window,
        "memory_content_sha256": memory_content_sha256,
        "crawler_event_count": crawler_count,
    }
    expected_stage = "24h" if stage == "24h" else "7d"
    stage_attempts = [
        row for row in attempts_raw if str(row["stage"]) == expected_stage
    ]
    if len(stage_attempts) > 1:
        _fail("attempt_readback")
    failure = {
        "stage": expected_stage,
        "status": str(stage_attempts[0]["status"]) if stage_attempts else "",
        "error_code": str(stage_attempts[0]["error_code"] or "")
        if stage_attempts
        else "",
    }
    return {
        "snapshot": {
            "schema": checkpoint.SNAPSHOT_SCHEMA,
            "observed_at": _clock_text(observed),
            "observation_started_at": checkpoint.window_clock('anchor'),
            **checkpoint.observation_identity(),
            "production_config": {
                "crawler_enabled": config_enabled,
                "collection_suspended": False,
                "crawler_config_present": config_present,
                "crawler_config_sha256": _sha256(config_bytes) if config_present else None,
                "runtime_role": "xhs-http",
                "adapter": "spider_xhs_http",
            },
            "global_due": {"count": len(due), "rows": due},
            "target": target_payload,
            "attempts": {
                "target_count_24h": attempt_count_24h,
                "target_count_7d": attempt_count_7d,
                "global_started_count": int(global_attempts["started"]),
                "target_unknown_count": target_unknown,
                "global_unknown_count": int(global_attempts["unknown"]),
                "rows": attempts,
            },
            "non_target_tracked_notes_sha256": _sha256(
                _canonical_json(non_target_rows)
            ),
        },
        "private": {
            "config": {
                "present": config_present,
                "enabled": config_enabled,
                "suspended": False,
                "sha256": _sha256(config_bytes) if config_present else None,
                "value_b64": base64.b64encode(config_bytes).decode("ascii")
                if config_present
                else None,
                "updated_at": str(config_rows[0]["updated_at"])
                if config_present
                else None,
            },
            "safety": safety,
            "failure": failure,
            "audit": {
                "attempt_count": len(attempts),
                "crawler_event_count": crawler_count,
                "growth_record_count": growth_count,
                "user_memory_count": memory_count,
                "growth_action": growth_action,
                "memory_window": memory_window,
                "memory_content_sha256": memory_content_sha256,
                "ledger_sha256": _sha256(_canonical_json(ledger)),
            },
        },
    }


def _required_transition_environment() -> dict[str, str]:
    keys = {
        "transition_id": "NOTEAI_ITEM34_TRANSITION_ID",
        "original_present": "NOTEAI_ITEM34_ORIGINAL_PRESENT",
        "original_sha256": "NOTEAI_ITEM34_ORIGINAL_SHA256",
        "original_b64": "NOTEAI_ITEM34_ORIGINAL_B64",
        "original_updated_at": "NOTEAI_ITEM34_ORIGINAL_UPDATED_AT",
        "active_b64": "NOTEAI_ITEM34_ACTIVE_B64",
        "active_updated_at": "NOTEAI_ITEM34_ACTIVE_UPDATED_AT",
    }
    values = {key: os.environ.get(name, "") for key, name in keys.items()}
    if SHA256_RE.fullmatch(values["transition_id"]) is None:
        _fail("transition_environment")
    if values["original_present"] not in {"0", "1"}:
        _fail("transition_environment")
    if values["original_present"] == "1" and SHA256_RE.fullmatch(
        values["original_sha256"]
    ) is None:
        _fail("transition_environment")
    if values["original_present"] == "0" and (
        values["original_sha256"]
        or values["original_b64"]
        or values["original_updated_at"]
    ):
        _fail("transition_environment")
    return values


def _decode_b64(value: str, code: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception:
        _fail(code)


def _transition_clock(value: str, *, required: bool) -> str:
    if not value:
        if required:
            _fail("transition_environment")
        return ""
    if value != value.strip() or len(value) > 128:
        _fail("transition_environment")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        _fail("transition_environment")
    if parsed.tzinfo is None:
        _fail("transition_environment")
    return value


def _inner_config(phase: str) -> dict[str, Any]:
    if phase not in {"activate", "restore"}:
        _fail("transition_phase")
    values = _required_transition_environment()
    original_present = values["original_present"] == "1"
    original_raw = _decode_b64(values["original_b64"], "transition_environment")
    active_raw = _decode_b64(values["active_b64"], "transition_environment")
    original_updated_at = _transition_clock(
        values["original_updated_at"],
        required=original_present,
    )
    active_updated_at = _transition_clock(
        values["active_updated_at"],
        required=True,
    )
    if _sha256(active_raw) != _sha256(_canonical_json(ACTIVE_CONFIG)):
        _fail("transition_environment")
    if original_present and _sha256(original_raw) != values["original_sha256"]:
        _fail("transition_environment")
    expected_before_present = original_present if phase == "activate" else True
    expected_before_sha = values["original_sha256"] if phase == "activate" else _sha256(active_raw)
    expected_before_updated_at = (
        original_updated_at if phase == "activate" else active_updated_at
    )
    after_present = True if phase == "activate" else original_present
    after_raw = active_raw if phase == "activate" else original_raw
    after_updated_at = (
        active_updated_at if phase == "activate" else original_updated_at
    )
    connection = _connect(write=True)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                if cursor.fetchone()["current_user"] != "noteai_app":
                    _fail("config_write_role")
                cursor.execute(
                    "SELECT current_user,value_json,is_secret,updated_at "
                    "FROM system_settings "
                    "WHERE key='crawler_config' FOR UPDATE"
                )
                rows = cursor.fetchall()
                if len(rows) > 1:
                    _fail("config_write_role")
                before_present = bool(rows)
                before_raw = rows[0]["value_json"].encode("utf-8") if rows else b""
                before_sha = _sha256(before_raw) if rows else None
                before_updated_at = str(rows[0]["updated_at"]) if rows else ""
                if (
                    before_present != expected_before_present
                    or before_sha != (expected_before_sha or None)
                    or before_updated_at != expected_before_updated_at
                    or (rows and rows[0]["is_secret"] != 0)
                ):
                    _fail("config_compare_and_swap")
                if phase == "activate" and not rows:
                    cursor.execute(
                        "INSERT INTO system_settings(key,value_json,is_secret,updated_at) "
                        "VALUES('crawler_config',%s,0,%s)",
                        (active_raw.decode("utf-8"), active_updated_at),
                    )
                elif phase == "activate":
                    cursor.execute(
                        "UPDATE system_settings SET value_json=%s,is_secret=0,"
                        "updated_at=%s WHERE key='crawler_config'",
                        (active_raw.decode("utf-8"), active_updated_at),
                    )
                elif original_present:
                    cursor.execute(
                        "UPDATE system_settings SET value_json=%s,is_secret=0,"
                        "updated_at=%s WHERE key='crawler_config'",
                        (original_raw.decode("utf-8"), original_updated_at),
                    )
                else:
                    cursor.execute(
                        "DELETE FROM system_settings WHERE key='crawler_config'"
                    )
                if cursor.rowcount != 1:
                    _fail("config_write")
        connection.commit()
    finally:
        connection.close()
    readback = _connect(write=False)
    try:
        with readback.transaction():
            with readback.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT value_json,is_secret,updated_at FROM system_settings "
                    "WHERE key='crawler_config'"
                )
                rows = cursor.fetchall()
    finally:
        readback.close()
    if after_present:
        if (
            len(rows) != 1
            or rows[0]["is_secret"] != 0
            or rows[0]["value_json"].encode("utf-8") != after_raw
            or str(rows[0]["updated_at"]) != after_updated_at
        ):
            _fail("config_readback")
    elif rows:
        _fail("config_readback")
    try:
        after_value = json.loads(after_raw.decode("utf-8")) if after_present else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("transition_environment")
    return {
        "transition_id": values["transition_id"],
        "phase": phase,
        "crawler_enabled": bool(after_value and after_value.get("enabled") is True),
        "collection_suspended": False,
        "before_config_present": before_present,
        "before_config_sha256": before_sha,
        "after_config_present": after_present,
        "after_config_sha256": _sha256(after_raw) if after_present else None,
        "configuration_mutations": 1,
        "other_configuration_mutations": 0,
    }


def _inner_safety_block(stage: str, track_id: str) -> dict[str, Any]:
    if stage not in STAGES:
        _fail("safety_stage")
    canonical_track_id = _canonical_uuid(track_id, "track_identity")
    expected_present_raw = os.environ.get(
        "NOTEAI_ITEM34_SAFETY_EXPECTED_PRESENT", ""
    )
    expected_sha = os.environ.get("NOTEAI_ITEM34_SAFETY_EXPECTED_SHA256", "")
    failure_code = os.environ.get("NOTEAI_ITEM34_SAFETY_FAILURE_CODE", "")
    blocked_at = _transition_clock(
        os.environ.get("NOTEAI_ITEM34_SAFETY_BLOCKED_AT", ""),
        required=True,
    )
    if (
        expected_present_raw not in {"0", "1"}
        or failure_code not in SESSION_BLOCK_ERROR_CODES
        or (
            expected_present_raw == "1"
            and SHA256_RE.fullmatch(expected_sha) is None
        )
        or (expected_present_raw == "0" and expected_sha)
    ):
        _fail("safety_environment")
    expected_present = expected_present_raw == "1"
    block_raw = _canonical_json(
        {
            "blocked_at": blocked_at,
            "reason_code": "server_session_logged_out",
            "session_blocked": True,
        }
    ).decode("ascii")
    connection = _connect(write=True)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                if cursor.fetchone()["current_user"] != "noteai_app":
                    _fail("safety_write_role")
                cursor.execute(
                    "SELECT value_json,is_secret FROM system_settings "
                    "WHERE key='xhs_collection_safety' FOR UPDATE"
                )
                rows = cursor.fetchall()
                if len(rows) > 1 or (rows and rows[0]["is_secret"] != 0):
                    _fail("safety_compare_and_swap")
                before_present = bool(rows)
                before_raw = str(rows[0]["value_json"]) if rows else ""
                before_sha = _sha256(before_raw.encode("utf-8")) if rows else None
                if (
                    before_present is not expected_present
                    or before_sha != (expected_sha or None)
                ):
                    _fail("safety_compare_and_swap")
                before = _collection_safety_projection(
                    before_raw if before_present else None
                )
                if before["session_blocked"] is True:
                    after_raw = before_raw
                    mutations = 0
                    status = "ALREADY_BLOCKED"
                elif rows:
                    cursor.execute(
                        "UPDATE system_settings SET value_json=%s,is_secret=0,"
                        "updated_at=%s WHERE key='xhs_collection_safety'",
                        (block_raw, blocked_at),
                    )
                    if cursor.rowcount != 1:
                        _fail("safety_write")
                    after_raw = block_raw
                    mutations = 1
                    status = "BLOCKED"
                else:
                    cursor.execute(
                        "INSERT INTO system_settings(key,value_json,is_secret,updated_at) "
                        "VALUES('xhs_collection_safety',%s,0,%s)",
                        (block_raw, blocked_at),
                    )
                    if cursor.rowcount != 1:
                        _fail("safety_write")
                    after_raw = block_raw
                    mutations = 1
                    status = "BLOCKED"
        connection.commit()
    finally:
        connection.close()
    readback = _connect(write=False)
    try:
        with readback.transaction():
            with readback.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT value_json,is_secret FROM system_settings "
                    "WHERE key='xhs_collection_safety'"
                )
                rows = cursor.fetchall()
    finally:
        readback.close()
    if (
        len(rows) != 1
        or rows[0]["is_secret"] != 0
        or str(rows[0]["value_json"]) != after_raw
        or _collection_safety_projection(str(rows[0]["value_json"]))[
            "session_blocked"
        ]
        is not True
    ):
        _fail("safety_readback")
    return {
        "schema": "noteai.item34.collection_safety_block.v1",
        "status": status,
        "track_identity_sha256": _sha256(
            f"noteai-item34-tracking-row-v1:{canonical_track_id}".encode("ascii")
        ),
        "reason_code": "server_session_logged_out",
        "failure_code": failure_code,
        "state_sha256": _sha256(after_raw.encode("utf-8")),
        "configuration_mutations": mutations,
        "provider_calls": 0,
        "secret_values_recorded": False,
    }


def _inner_schedule(track_id: str) -> dict[str, Any]:
    if checkpoint.current_observation() is not None:
        snapshot=_inner_snapshot('24h',track_id)['snapshot']
        target=snapshot['target']
        if (target['status']!='checking_7d' or target['check_24h_at'] is None
            or target['check_7d_at'] is not None or target['active_attempt_present']
            or target['claim_present'] or target['next_check_at']!=checkpoint.window_clock('3d')
            or snapshot['attempts']['target_count_24h']!=1
            or snapshot['attempts']['target_count_7d']!=0):
            _fail('observation_schedule_binding')
        # The generation-aware crawler already stored anchor+72h atomically.
        return {'track_id':track_id,'next_check_at':checkpoint.window_clock('3d'),
                'target_rows_mutated':0,'other_tracked_notes_row_mutations':0}
    connection = _connect(write=True)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user,next_check_at FROM tracked_notes WHERE "
                    "id=%s AND xhs_note_id=%s AND xhs_url=%s AND "
                    "status='checking_7d' AND check_24h_at IS NOT NULL AND "
                    "check_7d_at IS NULL AND active_attempt_id IS NULL AND "
                    "COALESCE(to_jsonb(tracked_notes)->>'observation_generation','0')='0' FOR UPDATE",
                    (track_id, checkpoint.CANONICAL_NOTE_ID, checkpoint.CANONICAL_URL),
                )
                rows = cursor.fetchall()
                if len(rows) != 1 or rows[0]["current_user"] != "noteai_app":
                    _fail("schedule_binding")
                cursor.execute(
                    "UPDATE tracked_notes SET next_check_at=%s WHERE id=%s",
                    (checkpoint.CHECKPOINT_3D_DUE_AT, track_id),
                )
                if cursor.rowcount != 1:
                    _fail("schedule_write")
        connection.commit()
    finally:
        connection.close()
    return {
        "track_id": track_id,
        "next_check_at": checkpoint.CHECKPOINT_3D_DUE_AT,
        "target_rows_mutated": 1,
        "other_tracked_notes_row_mutations": 0,
    }


def _inner_bind(track_id: str) -> dict[str, Any]:
    if checkpoint.current_observation() is not None:
        snapshot=_inner_snapshot('24h',track_id)['snapshot']
        target=snapshot['target']
        if (target['status']!='pending' or target['check_24h_at'] is not None
            or target['check_7d_at'] is not None or target['active_attempt_present']
            or target['claim_present'] or target['next_check_at']!=checkpoint.window_clock('24h')
            or snapshot['attempts']['target_count_24h']!=0
            or snapshot['attempts']['target_count_7d']!=0):
            _fail('observation_schedule_binding')
        return {'schema':'noteai.item34.tracking_schedule_bind.v1','status':'ALREADY_BOUND',
                'track_identity_sha256':_sha256(f'noteai-item34-tracking-row-v1:{track_id}'.encode('ascii')),
                'next_check_at':checkpoint.window_clock('24h'),'target_rows_mutated':0,
                'other_tracked_notes_row_mutations':0,'provider_calls':0,'secret_values_recorded':False,
                **checkpoint.observation_identity()}
    connection = _connect(write=True)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                if cursor.fetchone()["current_user"] != "noteai_app":
                    _fail("bind_write_role")
                cursor.execute(
                    "SELECT next_check_at FROM tracked_notes WHERE id=%s AND "
                    "xhs_note_id=%s AND xhs_url=%s AND status='pending' AND "
                    "check_24h_at IS NULL AND check_7d_at IS NULL AND "
                    "active_attempt_id IS NULL AND claim_token IS NULL AND "
                    "claim_expires_at IS NULL FOR UPDATE",
                    (track_id, checkpoint.CANONICAL_NOTE_ID, checkpoint.CANONICAL_URL),
                )
                rows = cursor.fetchall()
                if len(rows) != 1:
                    _fail("bind_target")
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM tracking_provider_attempts "
                    "WHERE track_id=%s",
                    (track_id,),
                )
                if int(cursor.fetchone()["count"]) != 0:
                    _fail("bind_prior_attempt")
                already = (
                    _clock_text(rows[0]["next_check_at"])
                    == checkpoint.CHECKPOINT_24H_DUE_AT
                )
                mutations = 0
                if not already:
                    cursor.execute(
                        "UPDATE tracked_notes SET next_check_at=%s WHERE id=%s",
                        (checkpoint.CHECKPOINT_24H_DUE_AT, track_id),
                    )
                    if cursor.rowcount != 1:
                        _fail("bind_write")
                    mutations = 1
        connection.commit()
    finally:
        connection.close()
    return {
        "schema": "noteai.item34.tracking_schedule_bind.v1",
        "status": "ALREADY_BOUND" if already else "BOUND",
        "track_identity_sha256": _sha256(
            f"noteai-item34-tracking-row-v1:{track_id}".encode("ascii")
        ),
        "next_check_at": checkpoint.CHECKPOINT_24H_DUE_AT,
        "target_rows_mutated": mutations,
        "other_tracked_notes_row_mutations": 0,
        "provider_calls": 0,
        "secret_values_recorded": False,
    }


def _provider_runtime_preflight() -> dict[str, Any]:
    """Return only non-secret local session and signer readiness facts."""

    try:
        from spider_xhs_http import (
            SessionCredentials,
            verify_pinned_signer_assets,
        )

        health = SessionCredentials.from_runtime_settings().public_health()
        assets = verify_pinned_signer_assets()
    except Exception:
        _fail("provider_runtime_preflight")
    if (
        not isinstance(health, dict)
        or health.get("configured") is not True
        or health.get("status") != "ready"
        or health.get("a1_present") is not True
        or health.get("auth_cookie_present") is not True
        or health.get("auth_cookie_expired") is not False
        or isinstance(health.get("cookie_count"), bool)
        or not isinstance(health.get("cookie_count"), int)
        or health["cookie_count"] < 2
        or not isinstance(assets, dict)
        or len(assets) < 1
    ):
        _fail("provider_runtime_preflight")
    return {
        "session_configured": True,
        "session_status": "ready",
        "session_cookie_count": int(health["cookie_count"]),
        "session_a1_present": True,
        "session_auth_cookie_present": True,
        "session_auth_cookie_expired": False,
        "signer_assets_verified": True,
        "signer_asset_count": len(assets),
        "secret_values_recorded": False,
    }


def _inner_role() -> dict[str, Any]:
    provider = _provider_runtime_preflight()
    connection = _connect(write=False)
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT current_user")
                current_user = cursor.fetchone()["current_user"]
                cursor.execute(
                    "SELECT key,is_secret FROM system_settings ORDER BY key"
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM tracking_provider_attempts "
                    "WHERE admitted_at::timestamptz>="
                    "date_trunc('day',clock_timestamp())"
                )
                daily_used = int(cursor.fetchone()["count"])
    finally:
        connection.close()
    daily_limit = 300
    if daily_used < 0 or daily_used >= daily_limit:
        _fail("tracking_daily_provider_limit")
    return {
        "current_user": current_user,
        "visible_setting_keys": [str(row["key"]) for row in rows],
        "visible_secret_rows": sum(int(row["is_secret"] != 0) for row in rows),
        "visible_unapproved_setting_rows": sum(
            int(row["key"] not in {"crawler_config", "xhs_collection_safety"})
            for row in rows
        ),
        **provider,
        "tracking_daily_provider_limit": daily_limit,
        "tracking_daily_provider_used": daily_used,
        "tracking_daily_provider_remaining": daily_limit - daily_used,
    }


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    run_parser.add_argument("--track-id", required=True)
    run_parser.add_argument("--image", required=True)
    bind_parser = subparsers.add_parser("bind")
    bind_parser.add_argument("--stage", choices=("24h",), required=True)
    bind_parser.add_argument("--track-id", required=True)
    bind_parser.add_argument("--image", required=True)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    reconcile_parser.add_argument("--track-id", required=True)
    reconcile_parser.add_argument("--image", required=True)
    for command in (run_parser,bind_parser,reconcile_parser):
        command.add_argument('--observation-binding',type=Path)
    for action in sorted(INNER_ACTIONS):
        inner = subparsers.add_parser(action, add_help=False)
        if action == "_config":
            inner.add_argument("phase", choices=("activate", "restore"))
            inner.add_argument("track_id")
        else:
            inner.add_argument("stage", choices=sorted(STAGES))
            inner.add_argument("track_id")
    args = parser.parse_args(argv)
    binding=_observation_environment()
    if getattr(args,'observation_binding',None) is not None:
        if binding is not None:_fail('duplicate_observation_binding')
        binding=_observation_file(args.observation_binding)
    with checkpoint.observation_context(binding):
        if binding is not None and args.track_id!=binding['track_id']:
            _fail('observation_row_binding')
        return _dispatch(args)


def _dispatch(args) -> int:
    if args.action == "run":
        value = _execute_host(args.stage, args.track_id, args.image)
    elif args.action == "bind":
        if os.geteuid() != 0:
            _fail("root_required")
        track_id = _canonical_uuid(args.track_id, "track_identity")
        with _exclusive_lock(LOCK_PATH):
            adapter = HostAdapter(image=args.image, stage=args.stage, track_id=track_id)
            value = adapter.bind_24h_schedule()
    elif args.action == "reconcile":
        if os.geteuid() != 0:
            _fail("root_required")
        track_id = _canonical_uuid(args.track_id, "track_identity")
        worker_name = _worker_name(args.stage)
        with _exclusive_lock(LOCK_PATH):
            quiescence = _quiesce_worker(worker_name,args.image)
            adapter = HostAdapter(image=args.image, stage=args.stage, track_id=track_id)
            snapshot = adapter.read_snapshot(phase="failure")
            attempts = [
                {
                    "stage": row["stage"],
                    "status": row["status"],
                    "identity_sha256": _attempt_digest(row["attempt_id"]),
                }
                for row in snapshot["attempts"]["rows"]
            ]
            if _service_state() != adapter.runtime_state:
                _fail("final_runtime_state")
            value = {
                "schema": "noteai.item34.tracking_reconciliation.v1",
                "stage": args.stage,
                "track_identity_sha256": _sha256(
                    f"noteai-item34-tracking-row-v1:{track_id}".encode("ascii")
                ),
                "target_status": snapshot["target"]["status"],
                "target_clocks": {
                    "next_check_at": snapshot["target"]["next_check_at"],
                    "check_24h_at": snapshot["target"]["check_24h_at"],
                    "check_7d_at": snapshot["target"]["check_7d_at"],
                },
                "attempts": attempts,
                "global_started_count": snapshot["attempts"]["global_started_count"],
                "global_unknown_count": snapshot["attempts"]["global_unknown_count"],
                "runtime_quiescence": quiescence,
                "provider_replay_allowed": False,
                "runtime_stopped": quiescence["after_running"] is False,
                "secret_values_recorded": False,
            }
    else:
        track_id = _canonical_uuid(args.track_id, "track_identity")
        if args.action == "_snapshot":
            value = _inner_snapshot(args.stage, track_id)
        elif args.action == "_config":
            value = _inner_config(args.phase)
        elif args.action == '_config_snapshot':
            value = _inner_config_snapshot()
        elif args.action == "_schedule":
            if args.stage != "24h":
                _fail("schedule_stage")
            value = _inner_schedule(track_id)
        elif args.action == "_bind":
            if args.stage != "24h":
                _fail("bind_stage")
            value = _inner_bind(track_id)
        elif args.action == "_role":
            value = _inner_role()
        else:
            value = _inner_safety_block(args.stage, track_id)
    sys.stdout.buffer.write(_canonical_json(value) + b"\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main(sys.argv[1:]))
    except (ProductionAdapterError, checkpoint.Item34CheckpointError) as exc:
        code = getattr(exc, "code", "rejected")
        sys.stderr.write(f"ITEM34_TRACKING_REJECTED code={code}\n")
        raise SystemExit(1)
