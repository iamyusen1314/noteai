#!/usr/bin/env python3
"""Offline managed Tracking preparation using the existing suspended unit.

No host command, environment file, database, supplier or observation is opened.
Inputs are separately reviewed Secret-free unit copies and restricted native
readbacks. This module's CLI only renders files; the existing durable launcher
has a separate managed action requiring future production authorization.
Returned controls are partial existing
managed_promotion fields and cannot issue terminal Evidence.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

if __package__:
    from .prepare_item36_private_bind import IMMUTABLE_IMAGE
else:
    from prepare_item36_private_bind import IMMUTABLE_IMAGE


TEMPLATE_SHA256 = "04f36a3b50829bd20775ef699459d7b577dbadd4d35ff2e1dba5cfe5ec179a00"
TOKEN = b"@@NOTEAI_XHS_IMAGE@@"
UNIT = "noteai-xhs-tracking.service"
CONTAINER = "noteai-xhs-tracking"
WORKER = ["python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "50"]
SHA256 = re.compile(r"[0-9a-f]{64}")
LEGACY_IMAGE = "sha256:a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
LEGACY_UNIT_SHA256 = "4392872f292a8caef960cc4f8eea34fed62791e783f6dcfc75f7655f2891f82d"
SERVICE_FIELDS = ("Id", "LoadState", "ActiveState", "SubState", "UnitFileState",
                  "Restart", "NRestarts", "MainPID", "InvocationID", "FragmentPath", "DropInPaths")
HOST_FIELDS = ("Memory", "NanoCpus", "PidsLimit", "ReadonlyRootfs", "CapDrop", "CapAdd",
               "Privileged", "SecurityOpt", "NetworkMode", "IpcMode", "RestartPolicy",
               "LogConfig", "PortBindings", "Tmpfs")


def container_projection_format():
    """Docker performs the restricted projection; full Env never leaves it."""
    fields = {key: "{{json ." + key + "}}" for key in ("Id", "Name", "Image", "RestartCount")}
    fields["State"] = '{"Running":{{json .State.Running}},"Pid":{{json .State.Pid}}}'
    fields["Config"] = ('{"Image":{{json .Config.Image}},"User":{{json .Config.User}},'
                        '"Cmd":{{json .Config.Cmd}},"Labels":{"com.noteai.service":'
                        '{{json (index .Config.Labels "com.noteai.service")}}}}')
    fields["HostConfig"] = "{" + ",".join(
        json.dumps(key) + ':{{json (index .HostConfig "' + key + '")}}' for key in HOST_FIELDS) + "}"
    fields["Suspended"] = "{{json (and $seen $suspended (not $conflict))}}"
    fields["Mounts"] = ('[{{range $i,$m := .Mounts}}{{if $i}},{{end}}'
                        '{"Type":{{json $m.Type}},"Source":{{json $m.Source}},'
                        '"Destination":{{json $m.Destination}},"RW":{{json $m.RW}}}{{end}}]')
    prefix = ('{{ $seen := false }}{{ $suspended := false }}{{ $conflict := false }}'
              '{{range .Config.Env}}{{if eq (index (split . "=") 0) "NOTEAI_XHS_COLLECTION_SUSPENDED"}}'
              '{{if $seen}}{{ $conflict = true }}{{end}}{{ $seen = true }}'
              '{{if eq . "NOTEAI_XHS_COLLECTION_SUSPENDED=1"}}{{ $suspended = true }}'
              '{{else}}{{ $conflict = true }}{{end}}{{end}}{{end}}')
    return prefix + "{" + ",".join(json.dumps(key) + ":" + value for key, value in fields.items()) + "}"


class NativeHostAdapter:
    """Bounded Linux host binding; constructing it executes nothing.

    The existing durable launcher's separate managed action calls this class;
    a future explicitly authorized caller must
    supply its private existing Journal directory. Tests inject a runner and
    filesystem root; they never invoke production commands. The shared lock
    is the existing Item34 sampler lock, not a new receipt or admission scheme.
    """
    def __init__(self, workdir: Path, *, root=Path("/"), runner=None):
        if root != Path("/") and runner is None:
            raise ValueError("isolated_root_requires_test_runner")
        if runner is not None and not callable(runner):
            raise ValueError("managed_runner_must_be_callable")
        self.root, self.workdir = root, workdir
        self.runner = subprocess.run if runner is None else runner
        self.unit = root / "etc/systemd/system" / UNIT
        self.lock = root / "run/lock/noteai-item34-tracking.lock"
        self.active = False
        self.original = self.candidate = None
        self.image_ref = self.image_id = None
        self.start_sent = self.stop_sent = False
        self.cid = self.invocation = None

    @contextmanager
    def locked(self):
        for directory in (self.workdir, self.lock.parent, self.unit.parent):
            metadata = directory.lstat()
            sticky_lock_directory = directory == self.lock.parent and metadata.st_mode & stat.S_ISVTX
            if (not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink()
                    or metadata.st_uid != os.geteuid()
                    or (metadata.st_mode & 0o022 and not sticky_lock_directory)):
                raise ValueError("managed_directory_identity")
        if self.workdir.stat().st_mode & 0o077 or (self.root == Path("/") and os.geteuid() != 0):
            raise ValueError("managed_private_owner_required")
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077):
                raise ValueError("managed_lock_identity")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with tempfile.TemporaryDirectory(prefix="managed-docker-", dir=self.workdir) as config:
                self.docker_config = config
                Path(config, "config.json").write_text('{"auths":{}}\n')
                self.active = True
                try:
                    yield
                finally:
                    self.active = False
        finally:
            os.close(fd)

    def _run(self, program, args, timeout=15):
        if not self.active:
            raise ValueError("managed_lock_required")
        argv = ["/usr/bin/" + program]
        if program == "docker":
            argv += ["--config", self.docker_config, "--host", "unix:///var/run/docker.sock"]
        try:
            result = self.runner(argv + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
                                 timeout=timeout, check=False)
            if result.returncode != 0 or len(result.stdout) > 65536:
                raise ValueError("managed_command_failed")
            return result.stdout.decode("utf-8", "strict").strip()
        except Exception:
            raise ValueError("managed_command_unknown") from None

    def unit_bytes(self):
        fd = os.open(self.unit, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o644
                    or not 0 < before.st_size <= 65536):
                raise ValueError("managed_unit_file_identity")
            content = os.read(fd, 65537)
            after = os.fstat(fd)
            path_state = self.unit.lstat()
            identity = lambda m: (m.st_dev, m.st_ino, m.st_size, m.st_mtime_ns, m.st_ctime_ns)
            if (identity(before) != identity(after) or identity(after) != identity(path_state)
                    or len(content) != before.st_size):
                raise ValueError("managed_unit_changed_during_read")
            return content
        finally:
            os.close(fd)

    def _service(self):
        raw = self._run("systemctl", ["show", UNIT, "--no-pager",
                                      "--property=" + ",".join(SERVICE_FIELDS + ("Job", "NeedDaemonReload"))])
        rows = [line.split("=", 1) for line in raw.splitlines()]
        if any(len(row) != 2 for row in rows) or len(rows) != len(SERVICE_FIELDS) + 2:
            raise ValueError("managed_service_readback")
        state = dict(rows)
        if set(state) != set(SERVICE_FIELDS + ("Job", "NeedDaemonReload")):
            raise ValueError("managed_service_readback")
        if (state["FragmentPath"] != "/etc/systemd/system/" + UNIT or state["DropInPaths"]
                or state["Id"] != UNIT or state["LoadState"] != "loaded"):
            raise ValueError("managed_service_drift")
        state["DropInPaths"] = []
        return state

    def _containers(self):
        # Include stopped same-name containers: --rm must not erase older work.
        raw = self._run("docker", ["ps", "-aq", "--no-trunc", "--filter", "name=^/" + CONTAINER + "$"])
        names = set(raw.splitlines()) if raw else set()
        labelled = self._run("docker", ["ps", "-aq", "--no-trunc", "--filter",
                                         "label=com.noteai.service=" + CONTAINER])
        names.update(labelled.splitlines() if labelled else [])
        if len(names) > 1 or any(SHA256.fullmatch(cid) is None for cid in names):
            raise ValueError("managed_container_residue")
        return [json.loads(self._run("docker", ["container", "inspect", "--format",
                                                container_projection_format(), cid])) for cid in sorted(names)]

    def stopped_state(self):
        state, containers = self._service(), self._containers()
        if (state["Job"] != "" or state["MainPID"] != "0" or containers
                or (state["UnitFileState"], state["ActiveState"], state["SubState"])
                != ("disabled", "inactive", "dead")):
            raise ValueError("managed_not_quiescent")
        content = self.unit_bytes()
        images = re.findall(rb"^ExecStartPre=/usr/bin/docker image inspect ([^\n]+)$", content, re.MULTILINE)
        if len(images) != 1:
            raise ValueError("managed_unit_image_readback")
        image = images[0].decode("ascii")
        return {"unit_sha256": digest(content), "image_ref": image,
                **{key: state[key] for key in ("UnitFileState", "ActiveState", "SubState")},
                "running_container_count": 0}

    def prepare_candidate(self, candidate, image_ref, image_id, original_image):
        state = self._service()
        if state["NeedDaemonReload"] != "no":
            raise ValueError("managed_manager_not_current")
        self.original, self.candidate = self.unit_bytes(), candidate
        self.original_image, self.image_ref, self.image_id = original_image, image_ref, image_id
        self.template = candidate.replace(image_ref.encode("ascii"), TOKEN)
        rendered, _original = render_unit(self.template, self.original,
                                          current_sha256=digest(self.original), current_image=original_image,
                                          candidate_image=image_ref)
        if rendered != candidate or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise ValueError("managed_candidate_binding")
        fmt = ('{"Id":{{json .Id}},"Os":{{json .Os}},"Architecture":{{json .Architecture}},'
               '"Entrypoint":{{json .Config.Entrypoint}},"RepoDigests":{{json .RepoDigests}},'
               '"Role":{{json (index .Config.Labels "com.noteai.runtime.role")}}}')
        value = json.loads(self._run("docker", ["image", "inspect", "--format", fmt, image_ref]))
        if (value["Id"] != image_id or value["Os"] != "linux" or value["Architecture"] != "amd64"
                or value["Entrypoint"] != ["/app/scripts/docker_entrypoint.sh"]
                or value["Role"] != "xhs-http" or image_ref not in value["RepoDigests"]):
            raise ValueError("managed_image_platform_binding")

    def replace_unit(self, expected_sha256, content):
        if not self.active or content not in (self.original, self.candidate) or content is None:
            raise ValueError("managed_unprepared_unit")
        if digest(self.unit_bytes()) != expected_sha256:
            raise ValueError("managed_unit_cas_conflict")
        fd, name = tempfile.mkstemp(prefix=".noteai-tracking-", dir=self.unit.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o644)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            if digest(self.unit_bytes()) != expected_sha256:
                raise ValueError("managed_unit_cas_conflict")
            os.replace(name, self.unit)
            directory = os.open(self.unit.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def reload(self):
        self._run("systemctl", ["daemon-reload"])
        if self._service()["NeedDaemonReload"] != "no":
            raise ValueError("managed_manager_not_current")

    def _binding(self, unit_sha, image_ref, image_id):
        if (self.unit_bytes() != self.candidate or digest(self.candidate) != unit_sha
                or (image_ref, image_id) != (self.image_ref, self.image_id)):
            raise ValueError("managed_candidate_drift")
        state = self._service()
        if state["NeedDaemonReload"] != "no":
            raise ValueError("managed_manager_not_current")
        if self.invocation and state["InvocationID"] not in (self.invocation, ""):
            raise ValueError("managed_invocation_drift")
        return state

    def start_once(self, unit_sha, image_ref, image_id):
        self._binding(unit_sha, image_ref, image_id)
        self.stopped_state()
        if self.start_sent:
            raise ValueError("managed_no_start_replay")
        self.start_sent = True
        self._run("systemctl", ["start", UNIT], timeout=190)
        self.invocation = self._service()["InvocationID"]

    def read_managed(self):
        state = self._binding(digest(self.candidate), self.image_ref, self.image_id)
        if state.pop("Job") != "":
            raise ValueError("managed_job_pending")
        state.pop("NeedDaemonReload")
        containers = self._containers()
        if len(containers) != 1:
            raise ValueError("managed_singleton")
        # Check ownership/controls before exec, using no purported health result.
        structural_health = {"status": "ready", "provider_called": False,
                             "active_provider_attempts": 0, "stale_provider_attempts": 0,
                             "unlinked_started_attempts": 0}
        validate_readback(state, containers, structural_health, template=self.template,
                          image_ref=self.image_ref, image_id=self.image_id,
                          unit_sha256=digest(self.unit_bytes()))
        self.cid = containers[0]["Id"]
        health = json.loads(self._run("docker", ["exec", self.cid, "python", "crawler_worker.py",
                                                 "--healthcheck"], timeout=20))
        return state, containers, health

    def stop_candidate(self, unit_sha, image_ref, image_id):
        self._binding(unit_sha, image_ref, image_id)
        containers = self._containers()
        for container in containers:
            if (container["Name"] != "/" + CONTAINER or container["Image"] != image_id
                    or container["Config"]["Image"] != image_ref
                    or container["Config"]["Labels"] != {"com.noteai.service": CONTAINER}
                    or (self.cid and container["Id"] != self.cid)):
                raise ValueError("managed_stop_ownership")
        if not self.start_sent or self.stop_sent:
            raise ValueError("managed_no_stop_replay")
        self.stop_sent = True
        # Even zero containers may hide an outstanding start job. Stop the
        # exact bound unit once, then independently require job/containers gone.
        self._run("systemctl", ["stop", UNIT], timeout=55)
        self.stopped_state()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render_unit(template: bytes, current_unit: bytes, *, current_sha256: str,
                current_image: str, candidate_image: str) -> tuple[bytes, bytes]:
    """Replace exactly the image inspect/run references; retain original bytes."""
    if digest(template) != TEMPLATE_SHA256 or template.count(TOKEN) != 2:
        raise ValueError("tracking_template_drift")
    if (IMMUTABLE_IMAGE.fullmatch(candidate_image) is None
            or (IMMUTABLE_IMAGE.fullmatch(current_image) is None
                and (current_image, current_sha256) != (LEGACY_IMAGE, LEGACY_UNIT_SHA256))):
        raise ValueError("immutable_image_required")
    if (digest(current_unit) != current_sha256
            or current_unit != template.replace(TOKEN, current_image.encode("ascii"))):
        raise ValueError("current_unit_drift")
    return template.replace(TOKEN, candidate_image.encode("ascii")), current_unit


def _keys(value, expected, error):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(error)


def _integer(value, *, positive=False):
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        value = int(value)
    if type(value) is not int or value < int(positive):
        raise ValueError("invalid_native_counter")
    return value


def validate_readback(service: dict, containers: list, health: dict, *,
                      template: bytes, image_ref: str, image_id: str,
                      unit_sha256: str) -> dict:
    """Validate a suspended managed instance, never the supplier/sample result.

    Docker input must project only these keys, never Config.Env. Suspended is
    the boolean result of matching the single non-secret literal
    NOTEAI_XHS_COLLECTION_SUSPENDED=1 inside the host-side projection.
    Source/provenance/freshness remain the authorized executor's responsibility.
    Config.Labels projects only com.noteai.service, retaining inherited OCI
    labels on the real container. Docker log bounds are checked here, but full
    log_controls also requires the existing host journald evidence.
    """
    if (IMMUTABLE_IMAGE.fullmatch(image_ref) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
            or SHA256.fullmatch(unit_sha256) is None):
        raise ValueError("artifact_binding")
    if (digest(template) != TEMPLATE_SHA256 or template.count(TOKEN) != 2
            or unit_sha256 != digest(template.replace(TOKEN, image_ref.encode("ascii")))):
        raise ValueError("managed_unit_image_binding")
    _keys(service, ("Id", "LoadState", "ActiveState", "SubState", "UnitFileState",
                    "Restart", "NRestarts", "MainPID", "InvocationID",
                    "FragmentPath", "DropInPaths"), "service_projection")
    if (service["Id"] != UNIT or service["LoadState"] != "loaded"
            or service["ActiveState"] != "active" or service["SubState"] != "running"
            or service["UnitFileState"] != "disabled"
            or service["FragmentPath"] != "/etc/systemd/system/" + UNIT
            or service["DropInPaths"] != []
            or not isinstance(service["InvocationID"], str)
            or re.fullmatch(r"[0-9a-f]{32}", service["InvocationID"]) is None
            or int(service["InvocationID"], 16) == 0):
        raise ValueError("managed_service_binding")
    _integer(service["MainPID"], positive=True)
    if service["Restart"] != "no" or _integer(service["NRestarts"]) != 0:
        raise ValueError("managed_restart_policy")
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("managed_singleton")
    container = containers[0]
    _keys(container, ("Id", "Name", "Image", "RestartCount", "State", "Config",
                      "HostConfig", "Suspended", "Mounts"), "container_projection")
    _keys(container["State"], ("Running", "Pid"), "state_projection")
    _keys(container["Config"], ("Image", "User", "Cmd", "Labels"), "config_projection")
    host = container["HostConfig"]
    _keys(host, ("Memory", "NanoCpus", "PidsLimit", "ReadonlyRootfs", "CapDrop",
                "CapAdd", "Privileged", "SecurityOpt", "NetworkMode", "IpcMode",
                "RestartPolicy", "LogConfig", "PortBindings", "Tmpfs"), "host_projection")
    config = container["Config"]
    if (not isinstance(container["Id"], str) or SHA256.fullmatch(container["Id"]) is None
            or container["Name"] != "/" + CONTAINER or container["Image"] != image_id
            or container["State"]["Running"] is not True
            or config["Image"] != image_ref or config["Cmd"] != WORKER
            or config["Labels"] != {"com.noteai.service": CONTAINER}
            or container["Suspended"] is not True):
        raise ValueError("managed_container_binding")
    _integer(container["State"]["Pid"], positive=True)
    if (config["User"] != "999:999" or host["ReadonlyRootfs"] is not True
            or host["CapDrop"] != ["ALL"] or host["CapAdd"] not in (None, [])
            or host["Privileged"] is not False
            or host["SecurityOpt"] != ["no-new-privileges:true"]
            or host["NetworkMode"] != "bridge" or host["IpcMode"] != "private"
            or host["PortBindings"] not in (None, {})
            or host["Tmpfs"] != {"/tmp": "rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999"}
            or container["Mounts"] != [{"Type": "bind", "Source": "/var/lib/noteai/data",
                                        "Destination": "/app/model/data", "RW": True}]
            or _integer(host["Memory"]) != 256 * 1024 * 1024
            or _integer(host["NanoCpus"]) != 250_000_000
            or _integer(host["PidsLimit"]) != 64):
        raise ValueError("managed_resource_controls")
    if (host["RestartPolicy"] != {"Name": "no", "MaximumRetryCount": 0}
            or type(host["RestartPolicy"].get("MaximumRetryCount")) is not int
            or _integer(container["RestartCount"]) != 0):
        raise ValueError("managed_restart_policy")
    if host["LogConfig"] != {"Type": "local", "Config": {"max-size": "10m", "max-file": "2"}}:
        raise ValueError("managed_log_controls")
    _keys(health, ("status", "active_provider_attempts", "stale_provider_attempts",
                   "unlinked_started_attempts", "provider_called"), "health_projection")
    if (health["status"] != "ready" or health["provider_called"] is not False
            or any(type(health[key]) is not int or health[key] != 0 for key in (
                "active_provider_attempts", "stale_provider_attempts", "unlinked_started_attempts"))):
        raise ValueError("managed_health_not_ready")
    identity = json.dumps({"service": service, "container_id": container["Id"],
                           "image_ref": image_ref, "image_id": image_id,
                           "unit_sha256": unit_sha256}, sort_keys=True, separators=(",", ":")).encode()
    return {"status": "INCOMPLETE", "singleton_winner_count": 1,
            "resource_controls": "PASS", "restart_controls": "PASS",
            "health_check": "PASS",
            "managed_service_identity_sha256": digest(identity)}


def verify_rollback(before: dict, after: dict) -> None:
    """Verify the exact initially stopped unit/config state after restoration."""
    keys = ("unit_sha256", "image_ref", "UnitFileState", "ActiveState", "SubState",
            "running_container_count")
    _keys(before, keys, "rollback_projection")
    _keys(after, keys, "rollback_projection")
    if (before["UnitFileState"] != "disabled" or before["ActiveState"] != "inactive"
            or before["SubState"] != "dead"
            or _integer(before["running_container_count"]) != 0
            or _integer(after["running_container_count"]) != 0
            or SHA256.fullmatch(before["unit_sha256"]) is None
            or (IMMUTABLE_IMAGE.fullmatch(before["image_ref"]) is None
                and (before["image_ref"], before["unit_sha256"]) != (LEGACY_IMAGE, LEGACY_UNIT_SHA256))
            or before != after):
        raise ValueError("managed_rollback_mismatch")


def rehearse(adapter, journal, *, template: bytes, current_image: str,
             candidate_image: str, image_id: str) -> dict:
    """Exercise the bounded sequence through an explicitly supplied adapter.

    The adapter must hold an exclusive unit
    lock for this entire call, bound every operation, CAS replace_unit against
    its expected hash, and stop_candidate only when exact unit/container/image
    ownership is confirmed. start_once must never retry. A timeout is UNKNOWN.
    Journal is the existing durable Journal; its caller owns close(). The
    original reviewed bytes are fsynced before any adapter mutation.

    Local tests use an in-memory host plus the real journal. This sequence
    cannot attest real rollback, log/alert delivery or a supplier attempt.
    """
    failures = []
    checks = None
    restored = False
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ValueError("artifact_binding")

    def record_safety(event, **data):
        try:
            journal.write(event, **data)
        except Exception:
            failures.append("journal_safety")

    with adapter.locked():
        before = adapter.stopped_state()
        verify_rollback(before, before)
        original = adapter.unit_bytes()
        candidate, rollback = render_unit(
            template, original, current_sha256=before["unit_sha256"],
            current_image=current_image, candidate_image=candidate_image,
        )
        if before["image_ref"] != current_image:
            raise ValueError("managed_original_image_binding")
        candidate_sha = digest(candidate)
        if candidate == original:
            raise ValueError("managed_candidate_unchanged")
        adapter.prepare_candidate(candidate, candidate_image, image_id, current_image)
        # A failure here prevents all mutations; never continue without a
        # durable exact original, including after an interrupted connection.
        journal.write("managed_original", state=before, unit=rollback.decode("utf-8"))
        apply_sent = start_sent = False
        step = "apply_intent"
        try:
            journal.write("managed_apply_intent", candidate_sha256=candidate_sha,
                          image_ref=candidate_image, image_id=image_id)
            step = "apply"
            apply_sent = True
            adapter.replace_unit(before["unit_sha256"], candidate)
            adapter.reload()
            if adapter.unit_bytes() != candidate:
                raise ValueError("managed_apply_readback")
            step = "start_intent"
            journal.write("managed_start_intent", candidate_sha256=candidate_sha)
            step = "start"
            start_sent = True
            adapter.start_once(candidate_sha, candidate_image, image_id)
            step = "health"
            service, containers, health = adapter.read_managed()
            checks = validate_readback(
                service, containers, health, template=template,
                image_ref=candidate_image, image_id=image_id,
                unit_sha256=digest(adapter.unit_bytes()),
            )
            step = "readback_journal"
            journal.write("managed_readback", partial=checks)
        except Exception:
            # Fixed step only; backend exception text may contain secrets.
            failures.append(step)
        finally:
            if apply_sent:
                if start_sent:
                    record_safety("managed_stop_intent", candidate_sha256=candidate_sha)
                    try:
                        adapter.stop_candidate(candidate_sha, candidate_image, image_id)
                    except Exception:
                        failures.append("stop")
                # A stop timeout never implies stopped. Restore only after an
                # independent safe-state read; do not overwrite concurrent drift.
                try:
                    stopped = adapter.stopped_state()
                    if (stopped["UnitFileState"] != "disabled"
                            or stopped["ActiveState"] != "inactive"
                            or stopped["SubState"] != "dead"
                            or _integer(stopped["running_container_count"]) != 0):
                        raise ValueError("managed_not_stopped")
                    current = adapter.unit_bytes()
                    if current not in (candidate, original):
                        raise ValueError("managed_restore_conflict")
                    record_safety("managed_restore_intent", original_sha256=before["unit_sha256"])
                    if current == candidate:
                        adapter.replace_unit(candidate_sha, original)
                    adapter.reload()
                    verify_rollback(before, adapter.stopped_state())
                    if adapter.unit_bytes() != original:
                        raise ValueError("managed_restore_bytes")
                    restored = True
                    record_safety("managed_restored", state=before)
                except Exception:
                    failures.append("restore")
        result = {"status": "UNKNOWN" if failures else "INCOMPLETE",
                  "restored": restored, "failed_steps": sorted(set(failures)),
                  "partial": checks}
        # A failed final fsync also prevents the caller reporting completion.
        record_safety("managed_local_result", result=result)
        if failures:
            result["status"] = "UNKNOWN"
            result["failed_steps"] = sorted(set(failures))
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--current-unit", type=Path, required=True)
    parser.add_argument("--current-sha256", required=True)
    parser.add_argument("--current-image", required=True)
    parser.add_argument("--candidate-image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.template, args.current_unit):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            parser.error("reviewed regular unit copy required")
    try:
        candidate, rollback = render_unit(
            args.template.read_bytes(), args.current_unit.read_bytes(),
            current_sha256=args.current_sha256, current_image=args.current_image,
            candidate_image=args.candidate_image,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(mode=0o700)
    for name, value in (("candidate.service", candidate), ("rollback.service", rollback)):
        with (args.output_dir / name).open("xb") as output:
            output.write(value)
        (args.output_dir / name).chmod(0o600)
    print("PREPARED_NOT_APPLIED readiness_credit=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
