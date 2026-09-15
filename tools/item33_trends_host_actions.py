"""Exact-unit host callbacks for the existing Item33 controller.

Nothing runs on import. This supplies only promote/rollback/reapply; production
DB/cycle and independent DML-capture readbacks must be wired separately. Missing
real dependencies cannot be bypassed by passing synthetic callback receipts.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import execute_item33_trends_promotion as controller


ACTION_ROOT = Path("/var/lib/noteai/item33-trends-promotion")
UNIT_PATH = Path("/etc/systemd/system/noteai-xhs-trends.service")
EXPECTED_INSTANCE_ID = "i-wz9bgztwf1tiakww2ops"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise controller.Item33ExecutionError("host_identity")


def _imds(path: str, *, method: str = "GET", headers=None) -> str:
    # Same proxy-free IMDSv2 identity pattern as the existing host deploy tools;
    # the short-lived metadata token is never written to a receipt or log.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request("http://100.100.100.200" + path,
        headers=headers or {}, method=method)
    try:
        with opener.open(request, timeout=3) as response:
            if response.status != 200:
                raise controller.Item33ExecutionError("host_identity")
            raw = response.read(4097)
        if len(raw) > 4096:
            raise controller.Item33ExecutionError("host_identity")
        return raw.decode("ascii").strip()
    except (OSError, UnicodeError, urllib.error.URLError):
        raise controller.Item33ExecutionError("host_identity") from None


def _assert_host_identity() -> None:
    token = _imds("/latest/api/token", method="PUT",
        headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"})
    if not token or len(token) > 256:
        raise controller.Item33ExecutionError("host_identity")
    instance_id = _imds("/latest/meta-data/instance-id",
        headers={"X-aliyun-ecs-metadata-token": token})
    if instance_id != EXPECTED_INSTANCE_ID:
        raise controller.Item33ExecutionError("host_identity")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run(argv: list[str]) -> bytes:
    result = subprocess.run(argv, check=False, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=240, env={"PATH": "/usr/bin:/bin"})
    if result.returncode != 0:
        raise controller.Item33ExecutionError("host_action_outcome_unknown")
    return result.stdout


def _regular(path: Path, *, mode: int | None = None) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != 0 or before.st_gid != 0
            or not 0 < before.st_size < 2 * 1024 * 1024
            or (stat.S_IMODE(before.st_mode) & 0o022)
            or (mode is not None and stat.S_IMODE(before.st_mode) != mode)):
            raise controller.Item33ExecutionError("host_file_metadata")
        raw = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
        linked = os.stat(path, follow_symlinks=False)
        if (len(raw) != before.st_size
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino)):
            raise controller.Item33ExecutionError("host_file_changed")
        return raw
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(path.parent)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


class Item33HostUnitActions:
    """One owner, three durable unit actions; no worker or DB direct dispatch."""

    def __init__(self, *, dependencies: Mapping[str, Any], clock=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # Must precede root/state/host access; the controller validates again.
        trusted = controller._load_verified_dependencies()
        self.item32_bucket = controller._validate_dependencies(dependencies, trusted)
        self._assert_day()

    def _assert_day(self) -> None:
        now = controller._trusted_now(self.clock)
        if now.date() <= self.item32_bucket:
            raise controller.Item33ExecutionError("utc_budget_not_available")

    def _assert_overlays(self) -> None:
        for path in (controller.RUNTIME_OVERLAY_ROOT, controller.RUNTIME_OVERLAY_ROOT / "model"):
            metadata = os.lstat(path)
            if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700):
                raise controller.Item33ExecutionError("runtime_overlay_directory")
        for name, digest in controller.RUNTIME_OVERLAY_SHA256.items():
            if _digest(_regular(controller.RUNTIME_OVERLAY_ROOT / name, mode=0o444)) != digest:
                raise controller.Item33ExecutionError("runtime_overlay_binding")

    def _replace_unit(self, before_sha: str, raw: bytes) -> None:
        if _digest(_regular(UNIT_PATH)) != before_sha:
            raise controller.Item33ExecutionError("unit_compare_and_swap")
        descriptor, temporary = tempfile.mkstemp(prefix=".noteai-item33-", dir=UNIT_PATH.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fchmod(handle.fileno(), 0o644)
                os.fsync(handle.fileno())
            if _digest(_regular(UNIT_PATH)) != before_sha:
                raise controller.Item33ExecutionError("unit_compare_and_swap")
            os.replace(temporary, UNIT_PATH)
            _sync_directory(UNIT_PATH.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _action(self, phase: str, authorization: Mapping[str, Any]) -> dict[str, Any]:
        self._assert_day()
        if os.geteuid() != 0:
            raise controller.Item33ExecutionError("root_required")
        if authorization.get("unit_name") != controller.UNIT_NAME:
            raise controller.Item33ExecutionError("unit_authorization")
        run_identity = controller._sha256(authorization.get("run_identity_sha256"), "run_identity")
        if authorization.get("automatic_retry_limit") != 0:
            raise controller.Item33ExecutionError("unit_authorization")
        _assert_host_identity()
        action_bucket = controller._trusted_now(self.clock).date().isoformat()
        if phase in {"promotion", "reapply"}:
            self._assert_overlays()
        if phase == "promotion":
            cycle_authorization = authorization.get("cycle_authorization")
            if (not isinstance(cycle_authorization, Mapping)
                or cycle_authorization.get("run_identity_sha256") != run_identity
                or cycle_authorization.get("bucket_key") != controller._trusted_now(self.clock).date().isoformat()
                or cycle_authorization.get("provider_request_limit") != 34
                or cycle_authorization.get("automatic_retry_limit") != 0):
                raise controller.Item33ExecutionError("unit_cycle_authorization")
            action_bucket = cycle_authorization["bucket_key"]
        fragment = _run(["systemctl", "show", controller.UNIT_NAME, "-p", "FragmentPath", "--value"])
        if fragment.decode().strip() != str(UNIT_PATH):
            raise controller.Item33ExecutionError("unit_fragment_binding")
        # No alternate entrypoint through a drop-in is allowed.
        if _run(["systemctl", "show", controller.UNIT_NAME, "-p", "DropInPaths", "--value"]).strip():
            raise controller.Item33ExecutionError("unit_dropin_present")
        if phase == "promotion":
            try:
                ACTION_ROOT.mkdir(mode=0o700, parents=False)
            except FileExistsError:
                pass
            else:
                _sync_directory(ACTION_ROOT.parent)
        metadata = os.lstat(ACTION_ROOT)
        if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != 0 or metadata.st_gid != 0):
            raise controller.Item33ExecutionError("action_root_metadata")
        lock = os.open(ACTION_ROOT / "executor.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            lock_metadata = os.fstat(lock)
            if (not stat.S_ISREG(lock_metadata.st_mode) or lock_metadata.st_nlink != 1
                or lock_metadata.st_uid != 0 or lock_metadata.st_gid != 0
                or stat.S_IMODE(lock_metadata.st_mode) != 0o600):
                raise controller.Item33ExecutionError("action_lock_metadata")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before_sha, after_sha = (
                (controller.PROMOTED_UNIT_SHA256, controller.SUSPENDED_UNIT_SHA256)
                if phase == "rollback" else
                (controller.SUSPENDED_UNIT_SHA256, controller.PROMOTED_UNIT_SHA256)
            )
            before = _regular(UNIT_PATH)
            if _digest(before) != before_sha:
                raise controller.Item33ExecutionError("unit_before_binding")
            if phase == "promotion":
                after = controller.render_managed_unit(before)
                if (ACTION_ROOT / "suspended-unit.rollback").exists():
                    raise controller.Item33ExecutionError("existing_action_requires_readback")
                _exclusive(ACTION_ROOT / "suspended-unit.rollback", before)
            else:
                original = json.loads(_regular(ACTION_ROOT / "promotion.started.json", mode=0o600))
                if original.get("run_identity_sha256") != run_identity:
                    raise controller.Item33ExecutionError("action_run_binding")
                if phase == "reapply":
                    prior = json.loads(_regular(ACTION_ROOT / "rollback.applied.json", mode=0o600))
                    if (prior.get("run_identity_sha256") != run_identity
                        or original.get("bucket_key") != controller._trusted_now(self.clock).date().isoformat()):
                        raise controller.Item33ExecutionError("reapply_bucket_or_rollback_binding")
                    action_bucket = original["bucket_key"]
                rollback = _regular(ACTION_ROOT / "suspended-unit.rollback", mode=0o600)
                if _digest(rollback) != controller.SUSPENDED_UNIT_SHA256:
                    raise controller.Item33ExecutionError("rollback_binding")
                after = rollback if phase == "rollback" else controller.render_managed_unit(rollback)
            record = {"phase": phase, "run_identity_sha256": run_identity,
                "bucket_key": action_bucket,
                "before_unit_sha256": before_sha, "after_unit_sha256": after_sha,
                "observed_at": controller._trusted_now(self.clock).isoformat(), "status": "STARTED_UNKNOWN"}
            # Never remove this marker, including on command/connection failure.
            _exclusive(ACTION_ROOT / f"{phase}.started.json", _json_bytes(record))
            self._replace_unit(before_sha, after)
            _run(["systemctl", "daemon-reload"])
            operation = "disable" if phase == "rollback" else "enable"
            # Slow host checks/reload may cross midnight. Never start a daemon
            # in a new provider bucket after the original action was admitted.
            if (phase != "rollback"
                and controller._trusted_now(self.clock).date().isoformat() != action_bucket):
                raise controller.Item33ExecutionError("start_bucket_expired")
            _run(["systemctl", operation, "--now", controller.UNIT_NAME])
            if _digest(_regular(UNIT_PATH)) != after_sha:
                raise controller.Item33ExecutionError("unit_after_binding")
            record["status"] = "APPLIED_REQUIRES_STATE_READBACK"
            record["completed_at"] = controller._trusted_now(self.clock).isoformat()
            raw = _json_bytes(record)
            _exclusive(ACTION_ROOT / f"{phase}.applied.json", raw)
            return {"phase": phase, "status": "applied", "unit_name": controller.UNIT_NAME,
                "before_unit_sha256": before_sha, "after_unit_sha256": after_sha,
                "mutation_count": 1, "other_unit_actions": 0,
                # This callback only changes a unit. The daemon's actual cycle
                # and DB writes require the separate real cycle/capture readers.
                "provider_calls": 0, "production_database_writes": 0,
                "canonical_result_sha256": _digest(raw)}
        finally:
            os.close(lock)

    def promote_unit(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        return self._action("promotion", authorization)

    def rollback_unit(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        return self._action("rollback", authorization)

    def reapply_unit(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        return self._action("reapply", authorization)
