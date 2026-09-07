#!/usr/bin/env python3
"""Offline managed Tracking preparation using the existing suspended unit.

No host command, environment file, database, supplier or observation is opened.
Inputs are separately reviewed Secret-free unit copies and restricted native
readbacks. The injectable rehearsal has no host implementation or CLI entry;
the CLI only renders files. Returned controls are partial existing
managed_promotion fields and cannot issue terminal Evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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

    No production adapter is included. The adapter must hold an exclusive unit
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
