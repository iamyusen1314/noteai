"""One temporary collector process in the existing fixed XHS image.

No import-time connections, provider calls, schema installation or service
mutation. The production entry point needs an explicit fixed config/deadline.
The surrounding original-F controller owns installation, promotion and recovery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import time

try:
    from . import item33_trends_runtime_capture as capture
except ImportError:
    import item33_trends_runtime_capture as capture


ROOT = Path("/var/lib/noteai/item33-trends-promotion/capture")
CONFIG = ROOT / "runtime-config.json"
MAX_SERVICE_SECONDS = 35 * 60


class CaptureServiceError(RuntimeError):
    """Fixed error code, never underlying connection or exception text."""


def require(condition, code):
    if not condition:
        raise CaptureServiceError(code)


def clock():
    return datetime.now(timezone.utc)


def safe_file(path, *, mode, maximum=1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
                and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == mode
                and 0 < before.st_size <= maximum, "control_file_metadata")
        raw = os.read(fd, before.st_size + 1)
        after = os.fstat(fd)
        linked = os.stat(path, follow_symlinks=False)
        require(len(raw) == before.st_size and (before.st_dev, before.st_ino) == (linked.st_dev, linked.st_ino)
                and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "control_file_changed")
        return raw
    finally:
        os.close(fd)


def run_service(*, config: dict, root: Path, deadline: datetime, connection_factory,
                catalog_reader, proof_builder, session_factory=capture.CaptureSession,
                now=clock, monotonic=time.monotonic, pause=time.sleep) -> dict:
    """Run once; request files never repeat work or reset a partial journal.

    Three independent injected autocommit connections isolate LISTEN, barrier
    notifications and rollback-only catalog inspection. The after-catalog read
    occurs inside seal's factory after durable admission closure/end barrier.
    """
    capture.validate_config(config)
    started = now().astimezone(timezone.utc)
    require(deadline.tzinfo is not None and started < deadline <= started + timedelta(seconds=MAX_SERVICE_SECONDS)
            and started.date().isoformat() == deadline.astimezone(timezone.utc).date().isoformat()
            == config["bucket_key"], "service_window")
    deadline = deadline.astimezone(timezone.utc)
    budget = min(MAX_SERVICE_SECONDS, (deadline - started).total_seconds())
    started_mono = monotonic()
    meta = root.lstat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == meta.st_gid == 0
            and stat.S_IMODE(meta.st_mode) == 0o700, "service_directory")
    binding = {"activation_identity_sha256": config["activation_identity_sha256"],
               "configuration_sha256": capture.sha(capture.encoded(config)), "bucket_key": config["bucket_key"]}
    start_record = {"schema": "noteai.item33.capture_service_start.v1", "state": "STARTED_UNKNOWN",
        **binding, "started_at": started.isoformat(), "deadline": deadline.isoformat(),
        "pid": os.getpid(), "provider_calls": 0, "schema_changes": 0, "secret_values_recorded": False}
    capture.exclusive(root / "service-started.json", capture.encoded(start_record) + b"\n")
    connections = []
    session = None
    try:
        for _ in range(3):
            conn = connection_factory()
            duplicate = any(conn is prior for prior in connections)
            if not duplicate:
                connections.append(conn)
            require(conn.autocommit is True and conn.info.transaction_status == 0
                    and not duplicate, "service_connection")
        listener, control, catalog_connection = connections
        before = catalog_reader(catalog_connection, config=config, now=now())
        # Validate the actual closure before READY; this pure self-comparison is
        # discarded and cannot substitute for the post-cycle catalog proof.
        proof_builder(before, before, config=config)
        session = session_factory(config, root, clock=now)
        session.start(listener, control)
        session.serve(root / "capture.sock")
        ready = {"schema": "noteai.item33.capture_service_ready.v1", "state": "LISTENING_READY",
            **binding, "observed_at": now().isoformat(), "pid": os.getpid(),
            "catalog_before": before, "provider_calls": 0, "schema_changes": 0, "secret_values_recorded": False}
        capture.exclusive(root / "service-ready.json", capture.encoded(ready) + b"\n")
        while True:
            current = now().astimezone(timezone.utc)
            require(started <= current <= deadline and current.date().isoformat() == config["bucket_key"]
                    and 0 <= monotonic() - started_mono <= budget, "service_deadline")
            require(not session.failure, "service_capture_unknown")
            request_path = root / "seal-request.json"
            if os.path.lexists(request_path):
                raw = safe_file(request_path, mode=0o600, maximum=4096)
                request = capture.decoded(raw)
                require(request == {"schema": "noteai.item33.capture_seal_request.v1", **binding}, "seal_request_binding")
                capture.exclusive(root / "seal-started.json", capture.encoded({**binding,
                    "state": "STARTED_UNKNOWN", "request_sha256": hashlib.sha256(raw).hexdigest()}) + b"\n")

                def finish_catalog():
                    after = catalog_reader(catalog_connection, config=config, now=now())
                    return proof_builder(before, after, config=config)

                seal = session.seal(control, catalog_proof_factory=finish_catalog)
                result = {"schema": "noteai.item33.capture_service_result.v1", "state": "SEALED",
                    **binding, "observed_at": now().isoformat(),
                    "run_identity_sha256": seal["run_identity_sha256"],
                    "capture_seal_sha256": hashlib.sha256(capture.encoded(seal) + b"\n").hexdigest(),
                    "provider_calls": 0, "schema_changes": 0, "secret_values_recorded": False}
                capture.exclusive(root / "service-result.json", capture.encoded(result) + b"\n")
                return result
            pause(0.25)
    except Exception:
        failure = {"schema": "noteai.item33.capture_service_result.v1", "state": "UNKNOWN_READBACK_ONLY",
            **binding, "observed_at": now().isoformat(), "error_code": "capture_service_unknown",
            "provider_calls": 0, "schema_changes": 0, "secret_values_recorded": False}
        try:
            capture.exclusive(root / "service-failure.json", capture.encoded(failure) + b"\n")
        except OSError:
            pass
        raise CaptureServiceError("capture_service_unknown") from None
    finally:
        cleanup_failed = False
        if session is not None:
            try:
                session.close()
            except Exception:
                cleanup_failed = True
        for conn in reversed(connections):
            try:
                conn.close()
            except Exception:
                cleanup_failed = True
        try:
            capture.exclusive(root / "service-close.json", capture.encoded({**binding,
                "state": "CLOSE_UNKNOWN" if cleanup_failed else "CONNECTIONS_CLOSED",
                "connection_count": len(connections), "observed_at": now().isoformat(),
                "secret_values_recorded": False}) + b"\n")
        except Exception:
            cleanup_failed = True
        if cleanup_failed:
            raise CaptureServiceError("capture_service_cleanup_unknown") from None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--deadline", required=True)
    args = parser.parse_args(argv)
    require(os.geteuid() == 0 and args.config == str(CONFIG), "service_entry")
    raw = safe_file(CONFIG, mode=0o444, maximum=65536)
    require(hashlib.sha256(raw).hexdigest() == args.config_sha256, "configuration_binding")
    config = capture.decoded(raw)
    require(raw == capture.encoded(config), "configuration_canonical")
    deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
    import psycopg
    try:
        from . import item33_trends_capture_catalog as catalog
    except ImportError:
        import item33_trends_capture_catalog as catalog
    # Existing runtime connection only; it is never an argument or receipt.
    dsn = os.environ.get("DATABASE_URL", "")
    require(bool(dsn), "database_binding_missing")
    result = run_service(config=config, root=ROOT, deadline=deadline,
        connection_factory=lambda: psycopg.connect(dsn, autocommit=True, connect_timeout=5,
            application_name="noteai-item33-capture"),
        catalog_reader=catalog.read_catalog_facts,
        proof_builder=lambda before, after, *, config: catalog.build_catalog_proof(before, after,
            config=config, source_sha256=hashlib.sha256(Path(catalog.__file__).read_bytes()).hexdigest()))
    print(json.dumps({"state": result["state"], "secret_values_output": False}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"state":"UNKNOWN_READBACK_ONLY","error_code":"capture_service_unknown","secret_values_output":false}')
        raise SystemExit(2)
