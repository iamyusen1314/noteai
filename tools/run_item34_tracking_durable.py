#!/usr/bin/env python3
"""Host-only durable logging for the unchanged, approved Item34 executor.

Run once under a non-restarting transient service. The root-only journal holds
native snapshots and non-secret crawler configuration for interrupted recovery.
It is not terminal Evidence and never permits replay. No env file is opened.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import execute_item34_tracking_checkpoint as checkpoint


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "deploy/production/execute_item34_tracking.py"
WRAPPER_SHA256 = "3d9e65c4535226a0a7d4c499558bff1d19ed69ebbbcf647a657700aff8c85e8a"
PROSPECTIVE_WRAPPER_SHA256 = "f8d614fd24cd3353d4629521e20a2a11287cee2a4f53e768cf0bd39766061125"


class Journal:
    def __init__(self, path: Path):
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
            raise ValueError("private_workdir_required")
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.failed = False
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        except Exception:
            os.close(self.fd)
            raise
        finally:
            os.close(directory)

    def write(self, event, **data):
        if self.failed:
            raise OSError("journal_previously_failed")
        raw = (json.dumps({"event": event, "recorded_at": datetime.now(timezone.utc).isoformat(),
                           **data}, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(self.fd, raw[offset:])
                if written <= 0:
                    raise OSError("journal_short_write")
                offset += written
            os.fsync(self.fd)
        except Exception:
            self.failed = True
            raise

    def close(self):
        os.close(self.fd)


class UnavailableJournal:
    """Only recovery may continue with failed storage; it remains UNKNOWN."""

    def write(self, event, **data):
        raise OSError(errno.EIO, "recovery_journal_unavailable")

    def close(self):
        pass


def load_wrapper(*, prospective=False):
    expected=PROSPECTIVE_WRAPPER_SHA256 if prospective else WRAPPER_SHA256
    if hashlib.sha256(WRAPPER.read_bytes()).hexdigest() != expected:
        raise ValueError("approved_wrapper_changed")
    spec = importlib.util.spec_from_file_location("item34_approved_wrapper", WRAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def logging_adapter(base, journal):
    class LoggingAdapter(base):
        def read_snapshot(self, *, phase):
            result = super().read_snapshot(phase=phase)
            try:
                journal.write("snapshot", phase=phase, snapshot=result, private=self.latest_private)
            except OSError:
                if phase != "failure":
                    raise
                # Preserve the original session-stop safety path even when the
                # journal is broken. Normal pre/post reads remain fail closed.
            return result

        def authorization(self):
            result = super().authorization()
            # This fsync must finish BEFORE activate or provider dispatch.
            journal.write("authorization", image=self.image, stage=self.stage,
                          track_id=self.track_id, initial_private=self.initial_private,
                          authorization=result, active_config_updated_at=self.active_config_updated_at,
                          **({'observation_binding':checkpoint.current_observation()}
                             if checkpoint.current_observation() is not None else {}))
            return result

        def transition(self, phase, authorization):
            if phase != "restore":
                journal.write("transition_intent", phase=phase)
                result = super().transition(phase, authorization)
                journal.write("transition_result", phase=phase, result=result)
                return result
            # A broken log must never prevent the already-authorized safety restore.
            try:
                journal.write("transition_intent", phase=phase)
            except OSError:
                pass
            result = super().transition(phase, authorization)
            journal.write("transition_result", phase=phase, result=result)
            return result

        def run_worker(self, argv):
            journal.write("worker_intent", argv=list(argv))
            result = super().run_worker(argv)
            journal.write("worker_result", result=result, worker=self.last_worker)
            return result

        def finish_worker_readback(self, snapshot):
            super().finish_worker_readback(snapshot)
            journal.write("worker_readback", snapshot=snapshot, worker=self.last_worker,
                          private=self.latest_private)

        def cleanup_known_worker(self):
            # Save the native readbacks before the original executor removes logs.
            journal.write("worker_cleanup", worker=self.last_worker, private=self.latest_private)
            return super().cleanup_known_worker()

    return LoggingAdapter


def execute(wrapper, journal, *, stage, track_id, image):
    original = wrapper.HostAdapter
    wrapper.HostAdapter = logging_adapter(original, journal)
    try:
        result = wrapper._execute_host(stage, track_id, image)
        journal.write("result", result=result)
        return result
    finally:
        wrapper.HostAdapter = original


def saved_authorization(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise ValueError("private_journal_required")
        states = []
        for line in source:
            # A crash tail is retained as UNKNOWN, never interpreted as a result.
            if not line.endswith(b"\n"):
                break
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                break
            if record.get("event") == "authorization":
                states.append(record)
    if len(states) != 1:
        raise ValueError("unique_saved_authorization_required")
    return states[0]


def config_identity(value):
    return {key: value.get(key) for key in ("present", "sha256", "updated_at", "value_b64")}


def restore(wrapper, journal, saved):
    stage, track_id, image = saved["stage"], saved["track_id"], saved["image"]
    if stage not in wrapper.STAGES:
        raise ValueError("stage")
    if saved.get('observation_binding')!=checkpoint.current_observation():
        raise ValueError('saved_observation_binding')
    binding=checkpoint.current_observation()
    if binding is not None and track_id!=binding['track_id']:
        raise ValueError('saved_observation_binding')
    # The original lock also excludes an active executor. Never generate a new
    # authorization timestamp; use the exact saved CAS state.
    log_failed = False

    def record(event, **data):
        nonlocal log_failed
        try:
            journal.write(event, **data)
        except OSError:
            log_failed = True

    with wrapper._exclusive_lock(wrapper.LOCK_PATH):
        name=wrapper._worker_name(stage) if checkpoint.current_observation() is not None else f"noteai-item34-tracking-{stage}"
        stopped = wrapper._quiesce_worker(name,image) if binding is not None else wrapper._quiesce_named_container(name)
        adapter = wrapper.HostAdapter(image=image, stage=stage, track_id=track_id)
        sampling_unknown=False
        def read_recovery_state():
            nonlocal sampling_unknown
            if binding is None:return adapter.read_snapshot(phase='failure')
            # Config recovery must remain reachable even when generation/history
            # makes sampling unverifiable. The saved exact CAS still controls it.
            private=adapter.read_config_snapshot()
            adapter.latest_private={'config':private['config']}
            try:return adapter.read_snapshot(phase='failure')
            except Exception:
                sampling_unknown=True
                adapter.latest_private={'config':private['config']}
                return {'sampling_acceptance':'UNKNOWN'}
        snapshot = read_recovery_state()
        original = saved["initial_private"]["config"]
        current = adapter.latest_private["config"]
        record("restore_readback", snapshot=snapshot, private=adapter.latest_private, stopped=stopped)
        changed = False
        if config_identity(current) != config_identity(original):
            active_hash = wrapper._sha256(wrapper._canonical_json(wrapper.ACTIVE_CONFIG))
            if (saved["authorization"] is None or current.get("present") is not True
                    or current.get("sha256") != active_hash
                    or current.get("updated_at") != saved["active_config_updated_at"]):
                raise ValueError("restore_compare_and_swap_conflict")
            adapter.initial_private = saved["initial_private"]
            adapter.active_config_updated_at = saved["active_config_updated_at"]
            adapter.transition_used = True
            record("restore_intent", active_config_updated_at=adapter.active_config_updated_at)
            result = adapter.transition("restore", saved["authorization"])
            # Read back even if result persistence fails; do not replay restore.
            snapshot = read_recovery_state()
            record("restore_result", result=result, snapshot=snapshot, private=adapter.latest_private)
            changed = True
        if config_identity(adapter.latest_private["config"]) != config_identity(original):
            raise ValueError("original_config_not_restored")
        if wrapper._service_state() != adapter.runtime_state:
            raise ValueError("final_runtime_state")
        result = {"configuration_restored": True, "configuration_write_used": changed,
                  "provider_replay_allowed": False, "provider_calls": 0,
                  "sampling_acceptance": "UNKNOWN" if sampling_unknown else "NOT_DETERMINED", "secret_values_recorded": False}
        record("result", result=result)
        if log_failed:
            raise OSError("restore_readback_not_durable")
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "restore", "managed"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--stage", choices=("24h", "3d"))
    parser.add_argument("--track-id")
    parser.add_argument("--image")
    parser.add_argument("--current-image")
    parser.add_argument("--image-id")
    parser.add_argument("--restore-from", type=Path)
    parser.add_argument('--observation-binding',type=Path)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError("root_required")
    if args.action == "managed":
        if (not all((args.image, args.current_image, args.image_id))
                or any((args.stage, args.track_id, args.restore_from,args.observation_binding))):
            raise ValueError("managed_arguments")
        return execute_managed(args)
    if args.current_image or args.image_id:
        raise ValueError("managed_arguments_require_managed_action")
    if args.action == "run" and (not all((args.stage, args.track_id, args.image)) or args.restore_from):
        raise ValueError("run_arguments")
    if args.action == "restore" and (not args.restore_from or any((args.stage, args.track_id, args.image,args.observation_binding))):
        raise ValueError("restore_arguments")
    saved = saved_authorization(args.restore_from) if args.action == "restore" else None
    binding=saved.get('observation_binding') if saved is not None else None
    prospective=bool(binding is not None or args.observation_binding is not None)
    wrapper=load_wrapper(prospective=True) if prospective else load_wrapper()
    if args.observation_binding is not None:binding=wrapper._observation_file(args.observation_binding)
    with checkpoint.observation_context(binding):
        if binding is not None and args.action=='run' and binding['track_id']!=args.track_id:
            raise ValueError('observation_row_binding')
        return _run_logged(args,wrapper,saved,prospective=prospective)


def _run_logged(args,wrapper,saved,*,prospective):
    journal = None
    try:
        journal = Journal(args.journal)
        journal.write("start", action=args.action, pid=os.getpid(),
                      wrapper_sha256=PROSPECTIVE_WRAPPER_SHA256 if prospective else WRAPPER_SHA256)
    except OSError as exc:
        if journal is not None:
            journal.close()
        # Do not bypass bad paths, permissions or an existing journal. Only
        # storage failure may defer recovery logging; run never gets this path.
        if args.action != "restore" or exc.errno not in {errno.EIO, errno.ENOSPC, errno.EDQUOT, errno.EROFS}:
            raise
        journal = UnavailableJournal()
    try:
        result = (execute(wrapper, journal, stage=args.stage, track_id=args.track_id, image=args.image)
                  if args.action == "run" else restore(wrapper, journal, saved))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or len(code) > 120 or not code.replace("_", "").isalnum():
            code = None
        try:
            journal.write("exception", exception_class=type(exc).__name__, code=code,
                          provider_replay_allowed=False)
        except OSError:
            pass
        raise
    finally:
        journal.close()


def execute_managed(args):
    """Separate managed-unit action; never load or execute the old sampler.

    This is an execution entry, not authorization. The existing plan currently
    keeps production PAUSED. A future owner-approved one-shot service may call
    it with the reviewed source and actual registry/config identities.
    """
    if __package__:
        from . import prepare_item34_managed_tracking as managed
    else:
        import prepare_item34_managed_tracking as managed
    template = ROOT / "deploy/production/systemd/noteai-xhs-tracking.service.template"
    journal = Journal(args.journal)
    try:
        journal.write("start", action="managed", pid=os.getpid(),
                      managed_source_sha256=hashlib.sha256(Path(managed.__file__).read_bytes()).hexdigest())
        adapter = managed.NativeHostAdapter(args.journal.parent)
        result = managed.rehearse(
            adapter, journal, template=template.read_bytes(), current_image=args.current_image,
            candidate_image=args.image, image_id=args.image_id,
        )
        journal.write("result", result=result)
        print(json.dumps(result, sort_keys=True))
        return 0 if (result["status"] == "INCOMPLETE" and result["restored"] is True
                     and result["failed_steps"] == []) else 1
    except Exception as exc:
        try:
            journal.write("exception", exception_class=type(exc).__name__, provider_replay_allowed=False)
        except OSError:
            pass
        raise
    finally:
        journal.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never print arbitrary exception text or private configuration.
        print(f"ITEM34_HOST_EXECUTION_UNKNOWN class={type(exc).__name__}; read journal and reconcile, do not replay",
              file=sys.stderr)
        raise SystemExit(1)
