"""Read-only Item33 host facts; no DB, health probe, provider or unit mutation.

The assembler must combine these facts with the independent database, physical
HTTP and capture receipts. A previous startup-health exit code is not a new
readiness query and is deliberately not called ``health=ready`` here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import execute_item33_trends_promotion as controller
import item33_trends_host_actions as actions


SESSION_PATH = Path("/etc/noteai/xhs-trends.env")
SESSION_SHA256 = "18f72f26971be0f578342ea7f8ae6336c7ee66ea67f6e7246b2b7d3866d26f6a"
RUN_ROOT = Path("/run")
SYSTEMD_ROOT = Path("/etc/systemd/system")
TASK_LABELS = ("item32-readonly", "item32-xhs-diagnostic", "item32-readonly-successor", "item33-trends-promotion")
INSPECTION_LABELS = ("item33-trends-inspection",)
FLAGS = {
    "NOTEAI_RUNTIME_ROLE": "xhs-http", "NOTEAI_DEPLOYMENT_STAGE": "production",
    "NOTEAI_CLOUD_RUNTIME": "1", "NOTEAI_XHS_SERVICE": "trends",
    "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
    "NOTEAI_XHS_COLLECTION_SUSPENDED": "0", "NOTEAI_XHS_FRESHNESS_REQUIRED": "1",
    "NOTEAI_XHS_SEARCH_SEEDS_PER_CATEGORY": "2", "NOTEAI_XHS_PROTOCOL": "pc_v5",
    "NOTEAI_XHS_V5_BUDGET_JSON": '{"initialization":2,"collection":34,"total":36}',
}
PROPERTIES = ("FragmentPath", "DropInPaths", "LoadState", "ActiveState", "SubState", "UnitFileState",
              "MainPID", "ControlPID", "ExecStartPost")
_SHA = re.compile(r"[0-9a-f]{64}")


def _fail(code: str):
    raise controller.Item33ExecutionError(code)


def _json(raw: bytes, code: str) -> Any:
    try:
        if not 1 <= len(raw) <= 512 * 1024:
            _fail(code)
        return json.loads(raw, parse_constant=lambda _: _fail(code))
    except (ValueError, UnicodeError):
        _fail(code)


def _ids(raw: bytes) -> list[str]:
    try:
        values = raw.decode("ascii").split()
    except UnicodeError:
        _fail("host_container_inventory")
    if len(values) > 100 or len(set(values)) != len(values) or any(not _SHA.fullmatch(value) for value in values):
        _fail("host_container_inventory")
    return values


def _inventory(run, *, label: str | None = None, name: str | None = None) -> list[str]:
    criterion = f"label={label}" if label is not None else f"name=^/{name}$"
    return _ids(run(["docker", "container", "ls", "-aq", "--no-trunc", "--filter", criterion]))


def _inspect_format() -> str:
    # Go template comparisons happen inside Docker. Env entries are never
    # returned, even for an unexpected/duplicate value: only fixed booleans.
    parts = []
    for key, value in FLAGS.items():
        prefix = key + "="
        parts.append('{{if eq (printf "%.' + str(len(prefix)) + 's" .) ' + json.dumps(prefix)
                     + '}}{"name":' + json.dumps(key) + ',"matches":{{if eq . '
                     + json.dumps(prefix + value) + '}}true{{else}}false{{end}}},{{end}}')
    return ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
            '"state":{{json .State}},"user":{{json .Config.User}},"entrypoint":{{json .Config.Entrypoint}},'
            '"cmd":{{json .Config.Cmd}},"mounts":{{json .Mounts}},'
            '"readonly_rootfs":{{json .HostConfig.ReadonlyRootfs}},'
            '"network_mode":{{json .HostConfig.NetworkMode}},"ipc_mode":{{json .HostConfig.IpcMode}},'
            '"memory":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},'
            '"pids_limit":{{json .HostConfig.PidsLimit}},"cap_drop":{{json .HostConfig.CapDrop}},'
            '"security_opt":{{json .HostConfig.SecurityOpt}},"ports":{{json .HostConfig.PortBindings}},'
            '"restart":{{json .HostConfig.RestartPolicy.Name}},'
            '"flags":[{{range .Config.Env}}' + ''.join(parts) + '{{end}}null]}')


def _session_digest(run) -> str:
    before = os.lstat(SESSION_PATH)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
        or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
        or not 0 < before.st_size < 65536):
        _fail("host_session_metadata")
    fields = run(["sha256sum", "--", str(SESSION_PATH)]).decode("ascii").split()
    after = os.lstat(SESSION_PATH)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_uid, item.st_gid,
                             item.st_nlink, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if fields != [SESSION_SHA256, str(SESSION_PATH)] or identity(before) != identity(after):
        _fail("host_session_binding")
    return fields[0]


def _image(run) -> None:
    template = ('{"id":{{json .Id}},"role":{{json (index .Config.Labels "com.noteai.runtime.role")}},'
                '"entrypoint":{{json .Config.Entrypoint}},"cmd":{{json .Config.Cmd}}}')
    value = _json(run(["docker", "image", "inspect", "--format", template,
                       "sha256:" + controller.V5_IMAGE_CONFIG_SHA256]), "host_image_readback")
    if value != {"id": "sha256:" + controller.V5_IMAGE_CONFIG_SHA256, "role": "xhs-http",
                 "entrypoint": ["/app/scripts/docker_entrypoint.sh"], "cmd": ["/bin/false"]}:
        _fail("host_image_binding")


def _unit(run) -> dict[str, str]:
    raw = run(["systemctl", "show", controller.UNIT_NAME, *[f"--property={key}" for key in PROPERTIES]])
    try:
        text = raw.decode("utf-8")
        rows = [line.split("=", 1) for line in text.splitlines() if line]
    except (UnicodeError, ValueError):
        _fail("host_unit_readback")
    if (len(rows) != len(PROPERTIES) or any(len(row) != 2 for row in rows)
        or {row[0] for row in rows} != set(PROPERTIES)):
        _fail("host_unit_readback")
    return dict(rows)


def _process_matches(pid: int, expected: list[str]) -> bool:
    """Compare fixed public argv in RAM; never return other process arguments."""
    if type(pid) is not int or pid <= 0:
        return False
    path = Path("/proc") / str(pid)
    try:
        before = (path / "stat").read_bytes()
        with (path / "cmdline").open("rb") as handle:
            raw = handle.read(8193)
        after = (path / "stat").read_bytes()
        # starttime is the 20th field after the parenthesized comm name.
        if before.rsplit(b")", 1)[1].split()[19] != after.rsplit(b")", 1)[1].split()[19]:
            return False
        actual = [item.decode("utf-8") for item in raw.rstrip(b"\0").split(b"\0")]
        return len(raw) <= 8192 and actual == expected
    except (OSError, ValueError, UnicodeError, IndexError):
        return False


def _startup_health_passed(value: str) -> bool:
    blocks = re.findall(r"\{([^{}]*)\}", value)
    target = "/usr/bin/docker exec noteai-xhs-trends python market_timing_worker.py --healthcheck"
    found = []
    for block in blocks:
        fields = dict(part.strip().split("=", 1) for part in block.split(";") if "=" in part)
        if fields.get("argv[]") == target:
            found.append(fields)
    return (len(found) == 1 and found[0].get("code") == "exited" and found[0].get("status") == "0"
            and re.fullmatch(r"[1-9][0-9]*", found[0].get("pid", "")) is not None)


def _mounts_valid(mounts: Any, *, normal: bool = False) -> bool:
    refs = tuple(controller.V5_RUNTIME_OVERLAY_SHA256)
    if not normal:
        refs += (*controller.V5_CAPTURE_TOOLS, controller.V5_CAPTURE_LAUNCHER_PATH)
    expected = {str(controller.V5_RUNTIME_OVERLAY_ROOT / name): "/app/" + name for name in refs}
    if not normal:
        expected[str(controller.V5_CAPTURE_ROOT / "runtime-config.json")] = "/run/noteai-item33/capture-config.json"
        expected[str(controller.V5_CAPTURE_ROOT / "capture.sock")] = "/run/noteai-item33/capture.sock"
    if not isinstance(mounts, list) or len(mounts) != len(expected):
        return False
    observed = {}
    for item in mounts:
        if (not isinstance(item, dict) or item.get("Type") != "bind" or item.get("RW") is not False
            or item.get("Source") in observed or item.get("Source") not in expected
            or item.get("Destination") != expected[item["Source"]]):
            return False
        observed[item["Source"]] = item["Destination"]
    return observed == expected


def _runtime_valid(value: Any, cid: str, process_matches, *, normal: bool = False) -> bool:
    if not isinstance(value, dict):
        return False
    flags = value.get("flags")
    if not isinstance(flags, list) or not flags or flags[-1] is not None:
        return False
    seen = set()
    for flag in flags[:-1]:
        if (not isinstance(flag, dict) or set(flag) != {"name", "matches"} or flag.get("name") not in FLAGS
            or flag.get("matches") is not True):
            return False
        seen.add(flag["name"])
    state = value.get("state") or {}
    command = ["python3", "-E", "-B", "/app/tools/item33_trends_runtime_capture.py", "--worker",
               "--config", "/run/noteai-item33/capture-config.json", "--", "--daemon", "--interval", "360"]
    cmd = ["/app/scripts/render_run_market_timing.sh"]
    if normal:
        cmd = command = ["python", "market_timing_worker.py", "--daemon", "--interval", "360"]
    return (seen == set(FLAGS) and value.get("id") == cid and value.get("name") == "/noteai-xhs-trends"
            and value.get("image") == "sha256:" + controller.V5_IMAGE_CONFIG_SHA256
            and value.get("user") == "999:999" and value.get("entrypoint") == ["/app/scripts/docker_entrypoint.sh"]
            and value.get("cmd") == cmd
            and value.get("readonly_rootfs") is True and value.get("network_mode") == "bridge"
            and value.get("ipc_mode") == "private" and value.get("memory") == 512 * 1024 * 1024
            and value.get("nano_cpus") == 500_000_000 and value.get("pids_limit") == 64
            and value.get("cap_drop") == ["ALL"] and value.get("security_opt") == ["no-new-privileges:true"]
            and value.get("ports") in ({}, None) and value.get("restart") == "no"
            and state.get("Running") is True and state.get("Paused") is False and state.get("Restarting") is False
            and _mounts_valid(value.get("mounts"), normal=normal) and process_matches(state.get("Pid"), command))


def _temporary_inventory() -> dict[str, int]:
    # The fixed retained source tree, action journal and capture directory are
    # permanent artifacts. Only the documented ephemeral namespaces are counted.
    runtime = sum(bool(re.fullmatch(r"noteai-item32-[a-z0-9_]{8}|noteai-item33-runtime-[a-z0-9_]{8}", path.name))
                  for path in RUN_ROOT.iterdir())
    staging = sum(bool(re.fullmatch(r"noteai-item33-stage-[a-z0-9_]{8}", path.name)) for path in RUN_ROOT.iterdir())
    units = sum(path.name.startswith("noteai-item33-") and path.name.endswith(".service") for path in SYSTEMD_ROOT.iterdir())
    dropins = sum(path.name.startswith(("noteai-item33-", "noteai-xhs-trends.service")) and path.name.endswith(".d")
                  for path in SYSTEMD_ROOT.iterdir())
    return {"runtime_directory_count": runtime, "stage_directory_count": staging,
            "temporary_unit_count": units, "temporary_dropin_count": dropins}


def _namespace_pid(host_pid: int) -> int:
    if type(host_pid) is not int or host_pid <= 0:
        _fail("host_capture_process")
    raw = Path(f"/proc/{host_pid}/status").read_text()
    rows = [line.split()[1:] for line in raw.splitlines() if line.startswith("NSpid:")]
    if len(rows) != 1 or not rows[0] or not all(value.isdecimal() for value in rows[0]):
        _fail("host_capture_process")
    if int(rows[0][0]) != host_pid:
        _fail("host_capture_process")
    return int(rows[0][-1])


def _capture_inventory(run, *, phase, binding, bound, now):
    ids = _inventory(run, label="com.noteai.task=item33-trends-capture")
    failure_path = controller.V5_CAPTURE_ROOT / "service-failure.json"
    try:
        os.lstat(failure_path)
        failed = True
    except FileNotFoundError:
        failed = False
    if failed or len(ids) != (1 if phase == "preflight" else 0):
        _fail("host_capture_container_or_failure")
    if not ids:
        return ids, failed, None
    bound._assert_capture({"capture_binding": binding})
    ready = _json(actions._regular(controller.V5_CAPTURE_ROOT / "service-ready.json", mode=0o600), "host_capture_ready")
    start = _json(actions._regular(controller.V5_CAPTURE_ROOT / "service-started.json", mode=0o600), "host_capture_ready")
    shared = {"activation_identity_sha256": binding["activation_identity_sha256"],
              "configuration_sha256": binding["configuration_sha256"], "bucket_key": now.date().isoformat()}
    if (ready.get("schema") != "noteai.item33.capture_service_ready.v1" or ready.get("state") != "LISTENING_READY"
        or start.get("schema") != "noteai.item33.capture_service_start.v1" or start.get("state") != "STARTED_UNKNOWN"
        or any(value.get(key) != expected for value in (ready, start) for key, expected in shared.items())
        or type(ready.get("pid")) is not int or ready["pid"] <= 0 or ready["pid"] != start.get("pid")
        or any(value.get("secret_values_recorded") is not False for value in (ready,start))
        or any(type(value.get(key)) is not int or value[key] != 0 for value in (ready,start) for key in ("provider_calls","schema_changes"))
        or not controller._clock(start.get("started_at"), "host_capture_ready")
            <= controller._clock(ready.get("observed_at"), "host_capture_ready") <= now
            < controller._clock(start.get("deadline"), "host_capture_ready")):
        _fail("host_capture_ready")
    config = _json(actions._regular(controller.V5_CAPTURE_ROOT / "runtime-config.json", mode=0o444), "host_capture_ready")
    from item33_trends_capture_catalog import digest, validate_catalog
    facts = ready.get("catalog_before", {})
    if (facts.get("catalog_sha256") != config.get("catalog_before_sha256")
        or digest(facts.get("catalog")) != config.get("catalog_before_sha256")
        or facts.get("server_enforced_read_only") is not True or facts.get("transaction_rolled_back") is not True):
        _fail("host_capture_ready")
    validate_catalog(facts["catalog"], config=config)
    template = ('{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},'
                '"paused":{{json .State.Paused}},"restarting":{{json .State.Restarting}},"pid":{{json .State.Pid}}}')
    observed = _json(run(["docker","container","inspect","--format",template,ids[0]]), "host_capture_process")
    if (observed.get("id") != ids[0] or observed.get("image") != "sha256:" + controller.V5_IMAGE_CONFIG_SHA256
        or observed.get("running") is not True or observed.get("paused") is not False or observed.get("restarting") is not False
        or _namespace_pid(observed.get("pid")) != ready["pid"]):
        _fail("host_capture_process")
    return ids, failed, observed


def read_host_facts(*, phase: str, dependencies: Mapping[str, Any], capture_binding: Mapping[str, Any],
                    clock=None, run=None, process_matches=None) -> dict[str, Any]:
    """Observe fixed F host state only. Does not assert unobserved DB/HTTP facts."""
    if phase not in {"preflight", "promoted", "rollback", "final", "normal"}:
        _fail("host_phase")
    clock = clock or (lambda: datetime.now(timezone.utc))
    run = run or actions._run
    process_matches = process_matches or _process_matches
    bound = actions.Item33HostUnitActions(dependencies=dependencies, capture_binding=capture_binding, clock=clock)
    if bound.runtime_profile != controller.V5_PROFILE or os.geteuid() != 0:
        _fail("host_runtime_profile")
    actions._assert_host_identity()
    unit = _unit(run)
    if unit["FragmentPath"] != str(actions.UNIT_PATH) or unit["DropInPaths"] or unit["LoadState"] != "loaded":
        _fail("host_unit_binding")
    active = phase in {"promoted", "final", "normal"}
    normal = phase == "normal"
    expected_sha = controller.promoted_unit_sha256(controller.V5_PROFILE, normal=normal) if active else controller.SUSPENDED_UNIT_SHA256
    unit_raw = actions._regular(actions.UNIT_PATH, mode=0o644)
    if hashlib.sha256(unit_raw).hexdigest() != expected_sha:
        _fail("host_unit_binding")
    if (unit["ActiveState"] != ("active" if active else "inactive")
        or unit["SubState"] != ("running" if active else "dead")
        or unit["UnitFileState"] != ("enabled" if active else "disabled")
        or not re.fullmatch(r"[0-9]+", unit["MainPID"]) or unit["ControlPID"] != "0"):
        _fail("host_unit_state")
    _session_digest(run)
    _image(run)
    formal = _inventory(run, label="com.noteai.service=noteai-xhs-trends")
    named = _inventory(run, name="noteai-xhs-trends")
    if formal != named or len(formal) != (1 if active else 0):
        _fail("host_formal_container")
    task = set().union(*[set(_inventory(run, label="com.noteai.task=" + name)) for name in TASK_LABELS])
    inspection = set().union(*[set(_inventory(run, label="com.noteai.task=" + name)) for name in INSPECTION_LABELS])
    if task or inspection:
        _fail("host_task_container_present")
    capture_ids, capture_failed, capture_state = _capture_inventory(run, phase=phase, binding=capture_binding, bound=bound, now=controller._trusted_now(clock))
    pid = int(unit["MainPID"])
    startup_health = None
    if active:
        bound._assert_overlays(normal=normal)
        if not normal:
            bound._assert_capture({"capture_binding": capture_binding})
        inspected = _json(run(["docker", "container", "inspect", "--format", _inspect_format(), formal[0]]), "host_container_readback")
        line = next(line for line in unit_raw.decode().splitlines() if line.startswith("ExecStart="))
        if not _runtime_valid(inspected, formal[0], process_matches, normal=normal) or not process_matches(pid, shlex.split(line.split("=", 1)[1])):
            _fail("host_runtime_binding")
        startup_health = _startup_health_passed(unit["ExecStartPost"])
        if not startup_health:
            _fail("host_startup_health_unproven")
    elif pid != 0:
        _fail("host_unit_process")
    temporary = _temporary_inventory()
    if any(temporary.values()):
        _fail("host_temporary_artifact_present")
    if (_unit(run) != unit or hashlib.sha256(actions._regular(actions.UNIT_PATH, mode=0o644)).hexdigest() != expected_sha
        or _inventory(run, label="com.noteai.service=noteai-xhs-trends") != formal
        or _inventory(run, name="noteai-xhs-trends") != named):
        _fail("host_readback_changed")
    _session_digest(run)
    if _capture_inventory(run, phase=phase, binding=capture_binding, bound=bound, now=controller._trusted_now(clock)) != (capture_ids, capture_failed, capture_state):
        _fail("host_readback_changed")
    if active:
        final_inspect = _json(run(["docker", "container", "inspect", "--format", _inspect_format(), formal[0]]), "host_container_readback")
        if final_inspect != inspected:
            _fail("host_readback_changed")
    result = {"schema": "noteai.item33.host_facts.v1", "phase": phase,
        "observed_at": controller._trusted_now(clock).isoformat(), "host": "noteai-api-f",
        "activation_identity_sha256": capture_binding["activation_identity_sha256"],
        "unit_sha256": expected_sha, "unit_active": unit["ActiveState"], "unit_sub": unit["SubState"],
        "unit_enabled": unit["UnitFileState"], "collection_suspended": not active,
        "formal_unit_count": 1, "formal_container_count": len(formal), "process_count": 1 if active else 0,
        "container_identity_sha256": hashlib.sha256(formal[0].encode()).hexdigest() if formal else None,
        "session_env_sha256": SESSION_SHA256, "startup_healthcheck_succeeded": startup_health,
        "task_container_count": len(task), "inspection_container_count": len(inspection),
        "capture_container_count": len(capture_ids), "capture_service_failure_present": capture_failed, **temporary,
        "observation_provider_calls": 0, "observation_database_connections": 0, "observation_mutations": 0,
        "secret_values_recorded": False}
    result["canonical_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return result
