#!/usr/bin/env python3
"""Run actual PG16 tests in a new, exclusively owned Unix-socket-only cluster.

Requires an already available PG16 server bin directory. This runner performs no
downloads, package installation, provider calls or production connections. It
never uses/stops an existing cluster, VM or daemon. Artifacts remain outside the
repository. On completion it stops only its own cluster and removes that cluster
directory; logs and the test receipt remain in the explicitly selected log dir.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(args, log, *, environment=None, timeout=60):
    with Path(log).open("ab") as output:
        result = subprocess.run([str(arg) for arg in args], stdout=output, stderr=subprocess.STDOUT,
                                env=environment, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("isolated command failed; inspect task log")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, help="already available native PostgreSQL 16 bin directory")
    parser.add_argument("--logs", required=True, help="exclusive external log/artifact directory")
    parser.add_argument("--pg-share", help="explicit relocated PG16 share/postgresql@16 directory")
    args = parser.parse_args(argv)
    binary = Path(args.pg_bin).resolve()
    logs = Path(args.logs).resolve()
    if ROOT == logs or ROOT in logs.parents:
        raise SystemExit("test artifacts must be outside the repository")
    if not all((binary / name).is_file() for name in ("postgres", "initdb", "pg_ctl")):
        raise SystemExit("native postgres/initdb/pg_ctl binaries required")
    version = subprocess.run([str(binary / "postgres"), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if not version.startswith("postgres (PostgreSQL) 16."):
        raise SystemExit("PostgreSQL 16 server required")
    logs.mkdir(parents=True, exist_ok=True)
    cluster = Path(tempfile.mkdtemp(prefix="na-amap-pg16-", dir="/tmp"))
    cluster.chmod(0o700)
    data, socket = cluster / "data", cluster / "socket"
    socket.mkdir(mode=0o700)
    suffix = uuid.uuid4().hex[:12]
    databases = ["noteai_amap_test_" + suffix + "_" + name for name in ("quota", "acl", "refresh")]
    port = 19432  # private Unix socket only; no TCP port is opened or shared
    marker = {"socket": str(socket), "port": port, "databases": databases}
    (cluster / "noteai-amap-fixture.json").write_text(json.dumps(marker))
    # Do not inherit any production DSN or provider credential. Keep only host
    # process/runtime essentials; tests set their own fixture-only observations.
    environment = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TMPDIR", "DYLD_LIBRARY_PATH") if name in os.environ}
    environment.update(NOTEAI_AMAP_REAL_PG_TEST="1", NOTEAI_AMAP_REAL_PG_SOCKET=str(socket),
        NOTEAI_AMAP_REAL_PG_PORT=str(port), NOTEAI_AMAP_REAL_PG_QUOTA_DB=databases[0],
        NOTEAI_AMAP_REAL_PG_ACL_DB=databases[1], NOTEAI_AMAP_REAL_PG_REFRESH_DB=databases[2],
        DATABASE_URL="postgresql:///offline_import_initialization_disabled", PYTHONPATH=str(ROOT),
        PYTHONUNBUFFERED="1", TZ="UTC", NOTEAI_FACT_SEARCH="0", NOTEAI_PUBLIC_PRODUCT="0")
    started = False
    cleanup_confirmed = False
    tests_passed = False
    failure = None
    result = None
    receipt = {"scope": "actual isolated local PostgreSQL 16; synthetic quota observations; no production",
               "server_version": version, "started_at": datetime.now(timezone.utc).isoformat(),
               "socket": str(socket), "databases": databases, "tcp_listen": False,
               "provider_requests": 0, "production_connections": 0,
               "schema_sha256": hashlib.sha256((ROOT / "model/migrations/postgres/0031_amap_shared_quota.sql").read_bytes()).hexdigest()}
    try:
        initialize = [binary / "initdb", "-D", data, "-U", "postgres", "--auth-local=trust", "--auth-host=reject",
                      "--encoding=UTF8", "--locale=C"]
        if args.pg_share:
            initialize.extend(["-L", str(Path(args.pg_share).resolve())])
        command(initialize, logs / "initdb.txt", environment=environment)
        with (data / "postgresql.conf").open("a") as config:
            config.write("\n# Exclusive acceptance fixture, no TCP listener\nlisten_addresses = ''\n")
            config.write("timezone = 'UTC'\nlog_timezone = 'UTC'\n")
            config.write("port = " + str(port) + "\nunix_socket_directories = '" + str(socket) + "'\n")
            config.write("unix_socket_permissions = 0700\nmax_connections = 100\nshared_buffers = '32MB'\n")
        command([binary / "pg_ctl", "-D", data, "-l", logs / "server.txt", "-w", "start"],
                logs / "start.txt", environment=environment)
        started = True
        import psycopg
        from psycopg import sql
        with psycopg.connect(host=str(socket), port=port, dbname="postgres", user="postgres", autocommit=True) as owner:
            version_num, address, listening = owner.execute("SELECT current_setting('server_version_num')::int, "
                                                          "inet_server_addr(),current_setting('listen_addresses')").fetchone()
            if not (160000 <= version_num < 170000 and address is None and listening == ""):
                raise RuntimeError("isolated PG16 socket assertion failed")
            for name in databases:
                owner.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        with (logs / "tests.txt").open("wb") as output:
            result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_amap_quota_real_postgres", "-v"],
                                    cwd=str(ROOT), env=environment, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=120, check=False)
        tests_passed = result.returncode == 0
        if not tests_passed:
            failure = "isolated PostgreSQL tests failed; inspect tests.txt"
    except Exception as exc:
        # No DSN/key/underlying SQL exception is printed into the receipt.
        failure = type(exc).__name__ + ": isolated setup/tests incomplete; inspect task logs"
    finally:
        if started or (data / "postmaster.pid").exists():
            try:
                pid_record = (data / "postmaster.pid").read_text().splitlines()
                if len(pid_record) < 2 or Path(pid_record[1]).resolve() != data.resolve():
                    raise RuntimeError("own cluster PID binding mismatch")
                command([binary / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], logs / "stop.txt", environment=environment)
                cleanup_confirmed = not (data / "postmaster.pid").exists() and not (socket / (".s.PGSQL."+str(port))).exists()
            except Exception:
                failure = "own-cluster cleanup unconfirmed; manual exact-path recovery required"
        else:
            cleanup_confirmed = True
        if cleanup_confirmed:
            shutil.rmtree(cluster)
        receipt.update(tests_passed=tests_passed, test_returncode=result.returncode if result is not None else None,
                       cleanup_confirmed=cleanup_confirmed, owned_cluster_path=str(cluster), failure=failure,
                       finished_at=datetime.now(timezone.utc).isoformat())
        (logs / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
    print(json.dumps({"tests_passed": tests_passed, "cleanup_confirmed": cleanup_confirmed,
                      "receipt": str(logs / "receipt.json"), "failure": failure}, ensure_ascii=False))
    return 0 if tests_passed and cleanup_confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
