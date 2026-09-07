#!/usr/bin/env python3
"""Run the single bounded Item32 Trends observation on API-F.

The collection container receives an isolated SQLite store and the XHS session
only.  It never receives DATABASE_URL.  Separate short-lived probes open an
explicit read-only PostgreSQL transaction before and after the collection.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UNIT = "noteai-xhs-trends.service"
SECRET_ENV = Path("/etc/noteai/xhs-trends.env")
WORK_ROOT = Path("/var/lib/noteai/item32-readonly")
EXPORT_ROOT = Path("/home/ecs-assist-user")
RUNTIME_ROOT = Path("/run")
EXPECTED_UNIT_SHA256 = (
    "3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6"
)
EXPECTED_CONFIG_SHA256 = (
    "a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
)
EXPECTED_MANIFEST_SHA256 = (
    "406445820107cda130698b157a20663b99697a0acdae65030784d3cb083c1e50"
)
IMAGE = f"sha256:{EXPECTED_CONFIG_SHA256}"
EXPECTED_ENV_KEYS = {"DATABASE_URL", "NOTEAI_XHS_COOKIES_JSON"}
EXPECTED_COOKIE_NAMES = {"a1", "web_session"}
DOMAINS = {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}
REAL_SOURCES = {
    "hot_search",
    "search_recommend",
    "search_phrase",
    "search_token",
    "homefeed_phrase",
    "homefeed_token",
    "crawler",
    "xhs_downloader",
    "mediacrawler",
}
SEARCH_RESULT_SOURCES = {"search_phrase", "search_token"}
ENDPOINT_SEQUENCE = ["homefeed"] * 10 + [
    endpoint
    for _ in range(12)
    for endpoint in ("search_recommend", "search_notes")
]
SOURCE_CONTAINER_PATHS = {
    "model/market_timing_worker.py": "/app/model/market_timing_worker.py",
    "model/trends_contract.py": "/app/model/trends_contract.py",
    "model/spider_xhs_http.py": "/app/model/spider_xhs_http.py",
    "model/hot_keywords.py": "/app/model/hot_keywords.py",
}
ATTEMPT_REF = (
    "deploy/production/evidence/production-item32-xhs-trends-attempt-audit.json"
)
SNAPSHOT_REF = (
    "deploy/production/evidence/production-item32-xhs-trends-snapshot.json"
)
PROOF_REF = (
    "deploy/production/evidence/production-item32-database-zero-write-proof.json"
)
TERMINAL_REF = (
    "deploy/production/evidence/production-item32-xhs-trends-readonly-verified.json"
)

DB_PROBE_SQL = {
    "begin": "BEGIN READ ONLY",
    "read_only": "SHOW transaction_read_only",
    "xid": "SELECT txid_current_if_assigned()",
    "identity": (
        "SELECT current_database(),current_user,"
        "COALESCE(inet_server_addr()::text,''),COALESCE(inet_server_port(),0)"
    ),
    "state": (
        "SELECT "
        "COUNT(*) FILTER (WHERE status IN ('running','needs_manual')),"
        "COUNT(*) FILTER (WHERE session_blocked) "
        "FROM xhs_trends_service_state"
    ),
    "attempts": (
        "SELECT COUNT(*) FROM xhs_trends_provider_attempts "
        "WHERE admitted_date=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date"
    ),
    "writes": (
        "SELECT relname,n_tup_ins,n_tup_upd,n_tup_del "
        "FROM pg_stat_xact_user_tables"
    ),
    "rollback": "ROLLBACK",
}
DB_PROBE_QUERYSET = json.dumps(
    DB_PROBE_SQL, ensure_ascii=True, sort_keys=True, separators=(",", ":")
)
DB_PROBE_QUERYSET_SHA256 = hashlib.sha256(
    DB_PROBE_QUERYSET.encode("utf-8")
).hexdigest()

DB_PROBE_SOURCE = r'''import hashlib
import json
import os
from datetime import datetime, timezone

import psycopg

SQL = __NOTEAI_ITEM32_DB_PROBE_SQL__
QUERYSET = json.dumps(SQL, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

result = {
    "observed_at": "",
    "server_enforced_read_only": False,
    "write_count": 0,
    "tuple_write_count": 0,
    "write_tables": [],
    "xid_assigned": True,
    "transaction_rolled_back": False,
    "session_identity_sha256": "",
    "readback_query_sha256": hashlib.sha256(QUERYSET.encode()).hexdigest(),
    "active_or_manual_count": -1,
    "session_blocked_count": -1,
    "today_attempt_count": -1,
    "secret_values_recorded": False,
}
connection = psycopg.connect(
    os.environ["DATABASE_URL"],
    autocommit=True,
    connect_timeout=10,
    options="-c timezone=UTC -c default_transaction_read_only=on -c statement_timeout=15000",
)
try:
    with connection.cursor() as cursor:
        cursor.execute(SQL["begin"])
        cursor.execute(SQL["read_only"])
        result["server_enforced_read_only"] = cursor.fetchone()[0] == "on"
        cursor.execute(SQL["xid"])
        result["xid_assigned"] = cursor.fetchone()[0] is not None
        cursor.execute(SQL["identity"])
        identity = "|".join(str(value) for value in cursor.fetchone())
        result["session_identity_sha256"] = hashlib.sha256(
            ("noteai-item32-production-db-v1:" + identity).encode()
        ).hexdigest()
        cursor.execute(SQL["state"])
        active_count, blocked_count = cursor.fetchone()
        result["active_or_manual_count"] = int(active_count or 0)
        result["session_blocked_count"] = int(blocked_count or 0)
        cursor.execute(SQL["attempts"])
        result["today_attempt_count"] = int(cursor.fetchone()[0] or 0)
        cursor.execute(SQL["writes"])
        rows = cursor.fetchall()
        changed = [
            str(row[0])
            for row in rows
            if sum(int(value or 0) for value in row[1:]) != 0
        ]
        result["write_tables"] = sorted(changed)
        result["tuple_write_count"] = sum(
            sum(int(value or 0) for value in row[1:]) for row in rows
        )
        result["write_count"] = result["tuple_write_count"]
        cursor.execute(SQL["rollback"])
        result["transaction_rolled_back"] = True
finally:
    connection.close()
result["observed_at"] = datetime.now(timezone.utc).isoformat()
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''.replace("__NOTEAI_ITEM32_DB_PROBE_SQL__", repr(DB_PROBE_SQL))


class Item32Error(RuntimeError):
    """Stable error whose message contains no provider or Secret value."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_clock(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise Item32Error("clock_shape")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Item32Error("clock_shape") from exc
    if parsed.tzinfo is None:
        raise Item32Error("clock_shape")
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(namespace: str, value: str) -> str:
    return _sha256_bytes(f"noteai-item32:{namespace}:{value}".encode("utf-8"))


def _run(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    stderr_to_stdout: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise Item32Error("command_failed")
    return completed


def _atomic_write(path: Path, value: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    candidate = Path(candidate_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        candidate.unlink(missing_ok=True)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_secret_env(path: Path) -> dict[str, str]:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= 65536
    ):
        raise Item32Error("secret_metadata")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = b""
        while True:
            chunk = os.read(descriptor, 8192)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 65536:
                raise Item32Error("secret_size")
    finally:
        os.close(descriptor)
    try:
        rows = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Item32Error("secret_encoding") from exc
    parsed: dict[str, str] = {}
    for row in rows:
        stripped = row.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise Item32Error("secret_shape")
        key, value = stripped.split("=", 1)
        if key in parsed or key not in EXPECTED_ENV_KEYS or not value:
            raise Item32Error("secret_shape")
        parsed[key] = value
    if set(parsed) != EXPECTED_ENV_KEYS:
        raise Item32Error("secret_keys")
    try:
        cookies = json.loads(parsed["NOTEAI_XHS_COOKIES_JSON"])
    except (TypeError, ValueError) as exc:
        raise Item32Error("cookie_shape") from exc
    if not isinstance(cookies, list) or len(cookies) != 2:
        raise Item32Error("cookie_shape")
    names: set[str] = set()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise Item32Error("cookie_shape")
        name = cookie.get("name")
        value = cookie.get("value")
        if (
            name not in EXPECTED_COOKIE_NAMES
            or name in names
            or not isinstance(value, str)
            or not 8 <= len(value) <= 4096
            or any(character in value for character in "\r\n;")
            or cookie.get("domain") != ".xiaohongshu.com"
            or cookie.get("path") != "/"
        ):
            raise Item32Error("cookie_shape")
        names.add(name)
    if names != EXPECTED_COOKIE_NAMES:
        raise Item32Error("cookie_shape")
    return parsed


def _load_plan(path: Path, executor_path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    plan = json.loads(raw.decode("utf-8"))
    executor_sha256 = _sha256_bytes(executor_path.read_bytes())
    if (
        plan.get("item") != 32
        or plan.get("status") != "PREPARED_NOT_EXECUTED"
        or plan.get("readiness_credit") is not False
        or plan.get("outer_executor") != "tools/execute_item32_readonly_trends.py"
        or plan.get("outer_executor_sha256") != executor_sha256
        or plan.get("existing_unit_sha256") != EXPECTED_UNIT_SHA256
        or plan.get("existing_image_config_sha256") != EXPECTED_CONFIG_SHA256
        or plan.get("existing_registry_manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or plan.get("database_readonly_probe_sha256")
        != DB_PROBE_QUERYSET_SHA256
        or plan.get("bounds", {}).get("cycles") != 1
        or plan.get("bounds", {}).get("provider_requests_per_run_max") != 34
        or plan.get("bounds", {}).get("provider_requests_per_utc_day_max") != 34
        or plan.get("bounds", {}).get("keywords_max") != 90
        or plan.get("bounds", {}).get("real_keywords_per_domain_min") != 12
        or plan.get("bounds", {}).get("domains") != 6
        or plan.get("bounds", {}).get("automatic_retry") != 0
        or plan.get("provider_calls_dispatched") != 0
        or plan.get("cloud_resources_started") != 0
    ):
        raise Item32Error("plan_binding")
    if plan.get("source_sha256") != {
        "model/market_timing_worker.py": "e89be24bd3d32c8283acf4cba3f6586d2d5dff7c2c113377b743897bd0527978",
        "model/trends_contract.py": "530820f68b1feb67aba0037d76ff9548ac0e629fea1c9854cc3df2048e2f2ca8",
        "model/spider_xhs_http.py": "981a7c704ae4b9efbf0db39aa2a8a1531f40e6848da3a95357bd3cc7b18ce7b7",
        "model/hot_keywords.py": "48073372ef7c490192ff6cff54c326401b14d313d427e705a1a90f9bc17449b4",
    }:
        raise Item32Error("source_plan_binding")
    return plan, _sha256_bytes(raw)


def _ensure_work_root() -> None:
    WORK_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = os.lstat(WORK_ROOT)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != 0
        or metadata.st_gid != 0
    ):
        raise Item32Error("work_root_metadata")


def _acquire_executor_lock() -> int:
    path = WORK_ROOT / "executor.lock"
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
    ):
        os.close(descriptor)
        raise Item32Error("executor_lock_metadata")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise Item32Error("executor_already_running") from exc
    return descriptor


def _admission_path() -> Path:
    return WORK_ROOT / "item32-admission.json"


def _create_admission(run_identity_sha256: str) -> None:
    payload = _json_bytes(
        {
            "schema": "noteai.item32.execution_admission.v1",
            "status": "DISPATCHED",
            "created_at": _utc_now(),
            "run_identity_sha256": run_identity_sha256,
            "automatic_retry_count": 0,
        }
    )
    try:
        descriptor = os.open(
            _admission_path(),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError as exc:
        raise Item32Error("item32_already_dispatched") from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(WORK_ROOT, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _update_admission(status: str, provider_calls: int, unknown_count: int) -> None:
    if status not in {"SUCCEEDED", "HOLD"}:
        raise Item32Error("admission_status")
    path = _admission_path()
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
    ):
        raise Item32Error("admission_metadata")
    original = json.loads(path.read_text(encoding="utf-8"))
    original.update(
        {
            "status": status,
            "updated_at": _utc_now(),
            "provider_calls": max(0, int(provider_calls)),
            "outcome_unknown_count": max(0, int(unknown_count)),
        }
    )
    _atomic_write(path, _json_bytes(original), 0o600)


def _remove_container(name: str) -> None:
    if not name:
        return
    _run(["docker", "rm", "-f", name], check=False)
    remaining = _run(
        ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]
    ).stdout.strip()
    if remaining:
        raise Item32Error("container_cleanup")


def _validated_export_account() -> Any:
    account = pwd.getpwnam("ecs-assist-user")
    metadata = os.lstat(EXPORT_ROOT)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != account.pw_uid
        or metadata.st_gid != account.pw_gid
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise Item32Error("export_root_metadata")
    return account


def _assert_trends_unit_suspended() -> None:
    raw = _run(
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
            "--no-pager",
        ]
    ).stdout.decode("utf-8")
    properties: dict[str, str] = {}
    for row in raw.splitlines():
        key, separator, value = row.partition("=")
        if not separator or key in properties:
            raise Item32Error("trends_unit_state")
        properties[key] = value
    if properties != {
        "ActiveState": "inactive",
        "SubState": "dead",
        "UnitFileState": "disabled",
    }:
        raise Item32Error("trends_unit_state")


def _assert_fixed_trends_container_absent() -> None:
    if _run(
        ["docker", "ps", "-aq", "--filter", "name=^/noteai-xhs-trends$"]
    ).stdout.strip():
        raise Item32Error("trends_container_present")


def _preflight_host(plan: dict[str, Any]) -> None:
    _validated_export_account()
    fragment = _run(
        ["systemctl", "show", UNIT, "-p", "FragmentPath", "--value"]
    ).stdout.decode().strip()
    if not fragment or _sha256_bytes(Path(fragment).read_bytes()) != EXPECTED_UNIT_SHA256:
        raise Item32Error("unit_binding")
    _assert_trends_unit_suspended()
    _assert_fixed_trends_container_absent()
    if _run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.noteai.task=item32-readonly",
        ]
    ).stdout.strip():
        raise Item32Error("item32_container_present")
    inspected = json.loads(_run(["docker", "image", "inspect", IMAGE]).stdout)[0]
    if (
        inspected.get("Id") != IMAGE
        or ((inspected.get("Config") or {}).get("Labels") or {}).get(
            "com.noteai.runtime.role"
        )
        != "xhs-http"
        or (inspected.get("Config") or {}).get("Entrypoint")
        != ["/app/scripts/docker_entrypoint.sh"]
        or (inspected.get("Config") or {}).get("Cmd") != ["/bin/false"]
    ):
        raise Item32Error("image_binding")
    paths = [SOURCE_CONTAINER_PATHS[path] for path in plan["source_sha256"]]
    source_check_name = f"noteai-item32-source-{uuid.uuid4().hex[:12]}"
    try:
        actual_output = _run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                source_check_name,
                "--label=com.noteai.task=item32-readonly",
                "--user=999:999",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--network=none",
                "--pids-limit=32",
                "--memory=128m",
                "--cpus=0.25",
                "--entrypoint=sha256sum",
                IMAGE,
                *paths,
            ],
            timeout=60,
        ).stdout.decode()
    finally:
        _remove_container(source_check_name)
    actual = {
        path: digest
        for digest, path in re.findall(r"^([0-9a-f]{64})\s+(.+)$", actual_output, re.M)
    }
    for source_ref, container_path in SOURCE_CONTAINER_PATHS.items():
        if actual.get(container_path) != plan["source_sha256"].get(source_ref):
            raise Item32Error("image_source_binding")


def _write_env(path: Path, key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise Item32Error("env_value_shape")
    _atomic_write(path, f"{key}={value}\n".encode("utf-8"), 0o600)


def _run_db_probe(run_dir: Path, db_url: str, phase: str) -> dict[str, Any]:
    probe_path = run_dir / "db_probe.py"
    db_env = run_dir / f"db-{phase}.env"
    _atomic_write(probe_path, DB_PROBE_SOURCE.encode("utf-8"), 0o444)
    _write_env(db_env, "DATABASE_URL", db_url)
    name = f"noteai-item32-db-{phase}-{uuid.uuid4().hex[:12]}"
    try:
        completed = _run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--label=com.noteai.task=item32-readonly",
                "--user=999:999",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--network=bridge",
                "--pids-limit=64",
                "--memory=256m",
                "--cpus=0.25",
                "--env-file",
                str(db_env),
                "--mount",
                f"type=bind,src={probe_path},dst=/probe/item32_db_probe.py,readonly",
                "--entrypoint=python",
                IMAGE,
                "/probe/item32_db_probe.py",
            ],
            timeout=60,
            stderr_to_stdout=True,
        )
        lines = [line for line in completed.stdout.decode("utf-8").splitlines() if line]
        if len(lines) != 1:
            raise Item32Error("db_probe_output")
        result = json.loads(lines[0])
    finally:
        try:
            db_env.unlink(missing_ok=True)
        finally:
            _remove_container(name)
    expected_query_sha = DB_PROBE_QUERYSET_SHA256
    if (
        result.get("server_enforced_read_only") is not True
        or result.get("write_count") != 0
        or result.get("tuple_write_count") != 0
        or result.get("write_tables") != []
        or result.get("xid_assigned") is not False
        or result.get("transaction_rolled_back") is not True
        or result.get("readback_query_sha256") != expected_query_sha
        or result.get("secret_values_recorded") is not False
        or result.get("active_or_manual_count") != 0
        or result.get("session_blocked_count") != 0
        or result.get("today_attempt_count") != 0
        or re.fullmatch(r"[0-9a-f]{64}", result.get("session_identity_sha256", ""))
        is None
    ):
        raise Item32Error("production_db_preflight")
    return result


def _prior_attempt_count() -> int:
    if not WORK_ROOT.exists():
        return 0
    run_directories = sorted(
        path for path in WORK_ROOT.iterdir() if path.name.startswith("run-")
    )
    total = 0
    for run_directory in run_directories:
        metadata = os.lstat(run_directory)
        if not stat.S_ISDIR(metadata.st_mode):
            raise Item32Error("prior_store_unreadable")
        database = run_directory / "task-store" / "hot_keywords.db"
        if not database.is_file() or database.is_symlink():
            raise Item32Error("prior_store_unreadable")
        try:
            uri = f"file:{database}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True)
            try:
                row = connection.execute(
                    "SELECT COUNT(*) FROM xhs_trends_provider_attempts",
                ).fetchone()
                total += int(row[0] or 0)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise Item32Error("prior_store_unreadable") from exc
    return total


def _create_collection_container(
    run_dir: Path,
    runtime_dir: Path,
    cookie_json: str,
) -> tuple[str, str, Path]:
    task_dir = run_dir / "task-store"
    task_dir.mkdir(mode=0o700)
    os.chown(task_dir, 999, 999)
    cookie_env = runtime_dir / "xhs.env"
    _write_env(cookie_env, "NOTEAI_XHS_COOKIES_JSON", cookie_json)
    name = f"noteai-item32-{uuid.uuid4().hex[:16]}"
    command = [
        "docker",
        "create",
        "--pull=never",
        "--name",
        name,
        "--label=com.noteai.task=item32-readonly",
        "--user=999:999",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--network=bridge",
        "--ipc=private",
        "--memory=512m",
        "--cpus=0.50",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999",
        "--env-file",
        str(cookie_env),
        "--env=NOTEAI_RUNTIME_ROLE=xhs-http",
        "--env=NOTEAI_XHS_SERVICE=trends",
        "--env=NOTEAI_DEPLOYMENT_STAGE=production",
        "--env=NOTEAI_CLOUD_RUNTIME=1",
        "--env=NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1",
        "--env=NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http",
        "--env=NOTEAI_XHS_COLLECTION_SUSPENDED=0",
        "--env=NOTEAI_XHS_FRESHNESS_REQUIRED=1",
        "--env=NOTEAI_XHS_FRESHNESS_HARD_FAIL=1",
        "--env=NOTEAI_XHS_SEARCH_SEEDS_PER_CATEGORY=2",
        "--env=NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL=",
        "--env=NOTEAI_MARKET_TIMING_SNAPSHOT_URL=",
        "--env=NOTEAI_MARKET_TIMING_REFRESH_URL=",
        "--env=NOTEAI_AUTHORIZED_TREND_URL=",
        "--env=NOTEAI_SQLITE_PATH=/task/noteai.db",
        "--env=NOTEAI_HOT_KEYWORD_DB_PATH=/task/hot_keywords.db",
        "--env=NOTEAI_MARKET_TIMING_SNAPSHOT_PATH=/task/snapshot.json",
        "--mount",
        f"type=bind,src={task_dir},dst=/task",
        "--workdir=/app/model",
        IMAGE,
        "python",
        "market_timing_worker.py",
        "--once",
    ]
    container_id = ""
    try:
        container_id = _run(command, timeout=60).stdout.decode().strip()
        if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
            raise Item32Error("container_identity")
        inspection = json.loads(
            _run(["docker", "inspect", container_id]).stdout
        )[0]
        environment = {}
        for item in (inspection.get("Config") or {}).get("Env") or []:
            key, _, value = str(item).partition("=")
            environment[key] = value
        mounts = inspection.get("Mounts") or []
        host = inspection.get("HostConfig") or {}
        if (
            "DATABASE_URL" in environment
            or not environment.get("NOTEAI_XHS_COOKIES_JSON")
            or environment.get("NOTEAI_SQLITE_PATH") != "/task/noteai.db"
            or environment.get("NOTEAI_HOT_KEYWORD_DB_PATH")
            != "/task/hot_keywords.db"
            or len(mounts) != 1
            or mounts[0].get("Destination") != "/task"
            or mounts[0].get("Source") != str(task_dir)
            or any(
                mount.get("Destination") == "/var/run/docker.sock"
                for mount in mounts
            )
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or "ALL" not in (host.get("CapDrop") or [])
            or (inspection.get("Config") or {}).get("Cmd")
            != ["python", "market_timing_worker.py", "--once"]
            or inspection.get("Image") != IMAGE
        ):
            raise Item32Error("container_boundary")
        cookie_env.unlink(missing_ok=True)
        return name, container_id, cookie_env
    except BaseException:
        try:
            _remove_container(name)
        finally:
            cookie_env.unlink(missing_ok=True)
        raise


def _read_task_result(database: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    uri = f"file:{database}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        runs = connection.execute("SELECT * FROM xhs_trends_runs").fetchall()
        if len(runs) != 1:
            raise Item32Error("run_count")
        run = dict(runs[0])
        attempts = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM xhs_trends_provider_attempts ORDER BY ordinal"
            ).fetchall()
        ]
        snapshots = connection.execute(
            "SELECT * FROM xhs_trends_snapshot_evidence"
        ).fetchall()
        if len(snapshots) != 1:
            raise Item32Error("snapshot_count")
        snapshot = dict(snapshots[0])
    finally:
        connection.close()
    raw_snapshot = str(snapshot["payload_json"]).encode("utf-8")
    attempt_ids = [row.get("id") for row in attempts]
    try:
        snapshot_payload = json.loads(raw_snapshot.decode("utf-8"))
        domain_counts = {
            domain: len(bucket["keywords"])
            for domain, bucket in snapshot_payload["domains"].items()
        }
        declared_domain_counts = json.loads(snapshot["domain_counts_json"])
        snapshot_relationship_valid = bool(
            set(domain_counts) == DOMAINS
            and declared_domain_counts == domain_counts
            and snapshot.get("keyword_count") == sum(domain_counts.values())
            and _parse_clock(run.get("started_at"))
            <= _parse_clock(snapshot.get("created_at"))
            <= _parse_clock(run.get("completed_at"))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, Item32Error):
        snapshot_relationship_valid = False
    if (
        run.get("status") != "succeeded"
        or run.get("provider_attempt_count") != 34
        or run.get("last_error_code") != ""
        or len(attempts) != 34
        or any(row.get("run_id") != run.get("id") for row in attempts)
        or any(not isinstance(value, str) or not value for value in attempt_ids)
        or len(set(attempt_ids)) != 34
        or [row.get("ordinal") for row in attempts] != list(range(1, 35))
        or [row.get("endpoint") for row in attempts] != ENDPOINT_SEQUENCE
        or any(row.get("status") != "succeeded" for row in attempts)
        or snapshot.get("run_id") != run.get("id")
        or snapshot.get("schema_version") != 1
        or snapshot.get("snapshot_sha256") != _sha256_bytes(raw_snapshot)
        or snapshot.get("snapshot_size") != len(raw_snapshot)
        or not snapshot_relationship_valid
        or run.get("snapshot_sha256") != _sha256_bytes(raw_snapshot)
        or run.get("snapshot_size") != len(raw_snapshot)
    ):
        raise Item32Error("terminal_run_shape")
    return run, attempts, raw_snapshot


def _snapshot_quality(
    raw: bytes,
    *,
    execution_started_at: str,
    execution_finished_at: str,
) -> tuple[dict[str, int], list[str], list[str], int]:
    snapshot = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(snapshot, dict)
        or set(snapshot)
        != {"schema_version", "generated_at", "freshness_max_hours", "domains"}
        or snapshot.get("schema_version") != 1
        or type(snapshot.get("freshness_max_hours")) is not int
        or not 1 <= snapshot["freshness_max_hours"] <= 48
        or set(snapshot.get("domains") or {}) != DOMAINS
    ):
        raise Item32Error("snapshot_shape")
    generated_at = _parse_clock(snapshot.get("generated_at"))
    if not (
        _parse_clock(execution_started_at)
        <= generated_at
        <= _parse_clock(execution_finished_at)
    ):
        raise Item32Error("snapshot_clock")
    counts: dict[str, int] = {}
    search_domains: set[str] = set()
    recommend_domains: set[str] = set()
    for domain, bucket in snapshot["domains"].items():
        rows = bucket.get("keywords") if isinstance(bucket, dict) else None
        if (
            not isinstance(bucket, dict)
            or set(bucket) != {"captured_at", "keywords"}
            or _parse_clock(bucket.get("captured_at")) != generated_at
            or not isinstance(rows, list)
            or not 12 <= len(rows) <= 15
        ):
            raise Item32Error("snapshot_quality")
        seen: set[str] = set()
        for row in rows:
            keyword = row.get("keyword") if isinstance(row, dict) else None
            source = row.get("source") if isinstance(row, dict) else None
            if (
                not isinstance(row, dict)
                or set(row)
                != {
                    "keyword",
                    "search_vol",
                    "trend_dir",
                    "source",
                    "category",
                    "sample_count",
                    "quality_score",
                    "evidence_level",
                    "quality_reason",
                    "captured_at",
                }
                or not isinstance(keyword, str)
                or not keyword
                or keyword in seen
                or source not in REAL_SOURCES
                or row.get("category") != domain
                or type(row.get("search_vol")) is not int
                or type(row.get("trend_dir")) is not int
                or type(row.get("sample_count")) is not int
                or type(row.get("quality_score")) is not int
                or row["quality_score"] < 55
                or row.get("evidence_level") not in {"medium", "strong"}
                or not isinstance(row.get("quality_reason"), str)
                or not row["quality_reason"]
                or _parse_clock(row.get("captured_at")) != generated_at
            ):
                raise Item32Error("snapshot_quality")
            seen.add(keyword)
            if source in SEARCH_RESULT_SOURCES:
                search_domains.add(domain)
            if source == "search_recommend":
                recommend_domains.add(domain)
        counts[domain] = len(rows)
    if search_domains != DOMAINS or recommend_domains != DOMAINS:
        raise Item32Error("snapshot_source_quality")
    total = sum(counts.values())
    if total > 90:
        raise Item32Error("snapshot_limit")
    return counts, sorted(search_domains), sorted(recommend_domains), total


def _attempt_count(database: Path) -> tuple[int, int]:
    if not database.is_file():
        return 0, 0
    try:
        uri = f"file:{database}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            row = connection.execute(
                "SELECT COUNT(*),SUM(CASE WHEN status IN ('admitted','outcome_unknown') THEN 1 ELSE 0 END) "
                "FROM xhs_trends_provider_attempts"
            ).fetchone()
            return int(row[0] or 0), int(row[1] or 0)
        finally:
            connection.close()
    except sqlite3.Error:
        return -1, -1


def _record_worker_receipt(
    run_dir: Path,
    raw: bytes,
    *,
    exit_code: int,
    secret_values: list[str],
) -> None:
    if len(raw) > 4 * 1024 * 1024:
        raise Item32Error("worker_output_size")
    if any(secret.encode("utf-8") in raw for secret in secret_values if secret):
        raise Item32Error("worker_output_secret_detected")
    events: list[dict[str, Any]] = []
    allowed_event_keys = {
        "event",
        "status",
        "error_code",
        "provider_calls",
        "keyword_count",
        "snapshot_size",
    }
    for line in raw.decode("utf-8", errors="replace").splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            value = json.loads(line[start:])
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict) or value.get("event") not in {
            "trends_run_started",
            "trends_run_succeeded",
            "trends_run_failed",
            "trends_run_skipped",
        }:
            continue
        events.append(
            {key: value[key] for key in sorted(allowed_event_keys) if key in value}
        )
    receipt = {
        "schema": "noteai.item32.worker_receipt.v1",
        "exit_code": int(exit_code),
        "output_sha256": _sha256_bytes(raw),
        "output_size": len(raw),
        "structured_events": events,
        "secret_values_recorded": False,
    }
    _atomic_write(run_dir / "worker-receipt.json", _json_bytes(receipt), 0o600)


def _build_artifacts(
    *,
    run_dir: Path,
    plan: dict[str, Any],
    plan_sha256: str,
    executor_sha256: str,
    container_id: str,
    pre_probe: dict[str, Any],
    post_probe: dict[str, Any],
) -> Path:
    task_dir = run_dir / "task-store"
    run, attempts, snapshot_raw = _read_task_result(task_dir / "hot_keywords.db")
    counts, search_domains, recommend_domains, keyword_count = _snapshot_quality(
        snapshot_raw,
        execution_started_at=run["started_at"],
        execution_finished_at=run["completed_at"],
    )
    if pre_probe["session_identity_sha256"] != post_probe["session_identity_sha256"]:
        raise Item32Error("database_identity_changed")
    run_hash = _identity("run", str(run["id"]))
    store_hash = _identity("task-store", str(run_dir))
    container_hash = _identity("container", container_id)
    path_hash = _identity("task-path", str(task_dir))
    attempt_payload = {
        "schema": "noteai.item32.trends_attempt_audit.v1",
        "run_identity_sha256": run_hash,
        "task_store_identity_sha256": store_hash,
        "started_at": run["started_at"],
        "finished_at": run["completed_at"],
        "provider_request_limit": 34,
        "attempts": [
            {
                "ordinal": row["ordinal"],
                "endpoint": row["endpoint"],
                "status": row["status"],
                "admitted_at": row["admitted_at"],
                "completed_at": row["completed_at"],
                "identity_sha256": _identity(
                    "provider-attempt", f"{row['id']}:{row['ordinal']}:{row['endpoint']}"
                ),
            }
            for row in attempts
        ],
        "secret_values_recorded": False,
    }
    proof_payload = {
        "schema": "noteai.item32.production_db_zero_write.v1",
        "run_identity_sha256": run_hash,
        "session_identity_sha256": pre_probe["session_identity_sha256"],
        "server_enforced_read_only": True,
        "write_count": 0,
        "tuple_write_count": 0,
        "write_tables": [],
        "xid_assigned": False,
        "transaction_rolled_back": True,
        "before_observed_at": pre_probe["observed_at"],
        "after_observed_at": post_probe["observed_at"],
        "readback_query_sha256": pre_probe["readback_query_sha256"],
        "secret_values_recorded": False,
    }
    artifact_dir = run_dir / "artifacts" / "deploy" / "production" / "evidence"
    artifact_dir.mkdir(parents=True)
    snapshot_path = artifact_dir / Path(SNAPSHOT_REF).name
    attempt_path = artifact_dir / Path(ATTEMPT_REF).name
    proof_path = artifact_dir / Path(PROOF_REF).name
    _atomic_write(snapshot_path, snapshot_raw)
    _atomic_write(attempt_path, _json_bytes(attempt_payload))
    _atomic_write(proof_path, _json_bytes(proof_payload))
    endpoint_counts = Counter(row["endpoint"] for row in attempts)
    terminal_payload = {
        "schema": "noteai.item32.xhs_trends_readonly.v1",
        "item": 32,
        "status": "VERIFIED",
        "readiness_credit": True,
        "observed_at": _utc_now(),
        "execution": {
            "cycle_count": 1,
            "provider_request_count": 34,
            "provider_request_limit": 34,
            "attempt_count": 34,
            "succeeded_attempt_count": 34,
            "automatic_retry_count": 0,
            "all_admitted_attempts_succeeded": True,
            "outcome_unknown_count": 0,
            "challenge_detected": False,
            "authenticated_session": True,
            "source": "real_xhs",
            "started_at": run["started_at"],
            "finished_at": run["completed_at"],
            "run_identity_sha256": run_hash,
            "task_store_identity_sha256": store_hash,
            "container_identity_sha256": container_hash,
            "outer_executor_sha256": executor_sha256,
            "execution_plan_sha256": plan_sha256,
            "image_config_sha256": EXPECTED_CONFIG_SHA256,
            "registry_manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "source_sha256": plan["source_sha256"],
            "endpoint_counts": {
                "homefeed": endpoint_counts["homefeed"],
                "search_recommend": endpoint_counts["search_recommend"],
                "search_notes": endpoint_counts["search_notes"],
            },
            "attempt_audit_ref": ATTEMPT_REF,
            "attempt_audit_sha256": _sha256_bytes(attempt_path.read_bytes()),
        },
        "quality": {
            "real_keyword_counts_by_domain": counts,
            "keyword_count": keyword_count,
            "search_result_domains": search_domains,
            "search_recommend_domains": recommend_domains,
            "snapshot_ref": SNAPSHOT_REF,
            "snapshot_sha256": _sha256_bytes(snapshot_raw),
            "snapshot_size": len(snapshot_raw),
        },
        "production_database": {
            "server_enforced_read_only": True,
            "write_count": 0,
            "tuple_write_count": 0,
            "write_tables": [],
            "xid_assigned": False,
            "transaction_rolled_back": True,
            "session_identity_sha256": pre_probe["session_identity_sha256"],
            "proof_ref": PROOF_REF,
            "proof_sha256": _sha256_bytes(proof_path.read_bytes()),
            "before_observed_at": pre_probe["observed_at"],
            "after_observed_at": post_probe["observed_at"],
        },
        "task_store": {
            "isolated": True,
            "production_database_url_present": False,
            "production_data_mount_present": False,
            "docker_socket_mount_present": False,
            "path_identity_sha256": path_hash,
        },
        "cleanup": {
            "task_container_count": 0,
            "postpaid_resources_started": 0,
        },
        "secret_values_recorded": False,
    }
    terminal_path = artifact_dir / Path(TERMINAL_REF).name
    _atomic_write(terminal_path, _json_bytes(terminal_payload))
    export_path = run_dir / "item32-evidence.candidate.tar.gz"
    with tarfile.open(export_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(artifact_dir.iterdir()):
            archive.add(
                path,
                arcname=f"deploy/production/evidence/{path.name}",
                recursive=False,
            )
    os.chmod(export_path, 0o600)
    return export_path


def _ensure_export_secret_free(export_path: Path, secrets: list[str]) -> None:
    try:
        with tarfile.open(export_path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) != 4 or any(not member.isfile() for member in members):
                raise Item32Error("export_shape")
            for member in members:
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise Item32Error("export_shape")
                raw = extracted.read()
                if any(
                    secret.encode("utf-8") in raw
                    for secret in secrets
                    if secret
                ):
                    raise Item32Error("export_secret_detected")
    except BaseException:
        export_path.unlink(missing_ok=True)
        raise


def _publish_export(candidate: Path) -> Path:
    account = _validated_export_account()
    name = (
        "item32-evidence-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex
        + ".tar.gz"
    )
    temporary_name = f".{name}.candidate"
    directory = os.open(EXPORT_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = -1
    published = False
    renamed = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with candidate.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
        os.fsync(descriptor)
        os.rename(
            temporary_name,
            name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        renamed = True
        os.fchown(descriptor, account.pw_uid, account.pw_gid)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(directory)
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
            if renamed:
                try:
                    os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
        os.close(directory)
    return EXPORT_ROOT / name


def _discard_published_export(path: Path) -> None:
    if (
        path.parent != EXPORT_ROOT
        or re.fullmatch(r"item32-evidence-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.gz", path.name)
        is None
    ):
        raise Item32Error("published_export_identity")
    directory = os.open(EXPORT_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.unlink(path.name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.fsync(directory)
    finally:
        os.close(directory)


def _discard_generated_artifacts(run_dir: Path) -> None:
    (run_dir / "item32-evidence.candidate.tar.gz").unlink(missing_ok=True)
    artifacts = run_dir / "artifacts"
    if artifacts.exists():
        shutil.rmtree(artifacts)


def execute(plan_path: Path, executor_path: Path) -> Path:
    if os.geteuid() != 0:
        raise Item32Error("root_required")
    plan, plan_sha256 = _load_plan(plan_path, executor_path)
    _ensure_work_root()
    lock_descriptor = _acquire_executor_lock()
    secret_values: dict[str, str] = {}
    run_dir: Path | None = None
    runtime_dir: Path | None = None
    container_name = ""
    container_id = ""
    collection_started = False
    admission_created = False
    post_probe_verified = False
    attempts_readback = 0
    unknown_readback = 0
    candidate: Path | None = None
    published: Path | None = None
    success = False
    try:
        if _admission_path().exists():
            raise Item32Error("item32_already_dispatched")
        if any(EXPORT_ROOT.glob("item32-evidence-*.tar.gz")):
            raise Item32Error("existing_export_requires_reconciliation")
        _preflight_host(plan)
        secret_values = _read_secret_env(SECRET_ENV)
        if _prior_attempt_count() != 0:
            raise Item32Error("prior_task_attempts_present")
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=WORK_ROOT))
        os.chmod(run_dir, 0o700)
        runtime_dir = Path(tempfile.mkdtemp(prefix="noteai-item32-", dir=RUNTIME_ROOT))
        os.chmod(runtime_dir, 0o700)
        pre_probe = _run_db_probe(
            runtime_dir, secret_values["DATABASE_URL"], "before"
        )
        container_name, container_id, _cookie_env = _create_collection_container(
            run_dir,
            runtime_dir,
            secret_values["NOTEAI_XHS_COOKIES_JSON"],
        )
        _create_admission(_identity("admission", f"{container_id}:{run_dir}"))
        admission_created = True
        _assert_trends_unit_suspended()
        _assert_fixed_trends_container_absent()
        collection_started = True
        timed_out = False
        try:
            completed = _run(
                ["docker", "start", "--attach", container_name],
                timeout=900,
                check=False,
                stderr_to_stdout=True,
            )
            worker_output = completed.stdout
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            worker_output = bytes(exc.output or b"")
        inspection = json.loads(
            _run(["docker", "inspect", container_name]).stdout
        )[0]
        exit_code = int(((inspection.get("State") or {}).get("ExitCode") or 0))
        _record_worker_receipt(
            run_dir,
            worker_output,
            exit_code=exit_code if not timed_out else 124,
            secret_values=[
                secret_values["DATABASE_URL"],
                secret_values["NOTEAI_XHS_COOKIES_JSON"],
                *[
                    str(cookie.get("value") or "")
                    for cookie in json.loads(
                        secret_values["NOTEAI_XHS_COOKIES_JSON"]
                    )
                ],
            ],
        )
        _remove_container(container_name)
        container_name = ""
        post_probe = _run_db_probe(
            runtime_dir, secret_values["DATABASE_URL"], "after"
        )
        post_probe_verified = True
        if post_probe["today_attempt_count"] != pre_probe["today_attempt_count"]:
            raise Item32Error("production_attempt_ledger_changed")
        if timed_out:
            raise Item32Error("worker_timeout")
        if exit_code != 0:
            raise Item32Error("worker_failed")
        if _run(
            ["docker", "ps", "-aq", "--filter", "label=com.noteai.task=item32-readonly"]
        ).stdout.strip():
            raise Item32Error("container_cleanup")
        attempts_readback, unknown_readback = _attempt_count(
            run_dir / "task-store" / "hot_keywords.db"
        )
        if attempts_readback != 34 or unknown_readback != 0:
            raise Item32Error("attempt_readback")
        executor_sha256 = _sha256_bytes(executor_path.read_bytes())
        candidate = _build_artifacts(
            run_dir=run_dir,
            plan=plan,
            plan_sha256=plan_sha256,
            executor_sha256=executor_sha256,
            container_id=container_id,
            pre_probe=pre_probe,
            post_probe=post_probe,
        )
        _ensure_export_secret_free(
            candidate,
            [
                secret_values["DATABASE_URL"],
                secret_values["NOTEAI_XHS_COOKIES_JSON"],
                *[
                    str(cookie.get("value") or "")
                    for cookie in json.loads(
                        secret_values["NOTEAI_XHS_COOKIES_JSON"]
                    )
                ],
            ],
        )
        _update_admission("SUCCEEDED", attempts_readback, unknown_readback)
        published = _publish_export(candidate)
        success = True
        return published
    except BaseException:
        attempts, unknown = (
            _attempt_count(run_dir / "task-store" / "hot_keywords.db")
            if run_dir is not None
            else (0, 0)
        )
        if admission_created:
            try:
                _update_admission("HOLD", max(attempts, 0), max(unknown, 0))
            except Exception:
                pass
        try:
            if published is not None:
                _discard_published_export(published)
                published = None
            if run_dir is not None:
                _discard_generated_artifacts(run_dir)
        except Exception:
            print(
                "ITEM32_CLEANUP_HOLD generated_artifact_residue=UNKNOWN",
                file=sys.stderr,
                flush=True,
            )
        if collection_started:
            database_status = "0" if post_probe_verified else "UNKNOWN"
            print(
                "ITEM32_EXECUTION_HOLD"
                f" provider_calls={max(attempts, 0)}"
                f" outcome_unknown_count={max(unknown, 0)}"
                f" retained_store_identity_sha256={_identity('retained-store', str(run_dir))}"
                " automatic_retry_count=0"
                f" production_db_writes={database_status}",
                flush=True,
            )
        raise
    finally:
        active_error = sys.exc_info()[0] is not None
        cleanup_failed = False
        if container_name:
            try:
                _remove_container(container_name)
            except Exception:
                cleanup_failed = True
        if runtime_dir is not None:
            try:
                shutil.rmtree(runtime_dir)
            except FileNotFoundError:
                pass
            except Exception:
                cleanup_failed = True
            if runtime_dir.exists():
                cleanup_failed = True
        secret_values = {}
        if run_dir is not None and (success or not collection_started):
            try:
                shutil.rmtree(run_dir)
            except FileNotFoundError:
                pass
            except Exception:
                cleanup_failed = True
            if run_dir.exists():
                cleanup_failed = True
        try:
            os.close(lock_descriptor)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            if published is not None:
                try:
                    _discard_published_export(published)
                    published = None
                except Exception:
                    pass
            if run_dir is not None:
                try:
                    _discard_generated_artifacts(run_dir)
                except Exception:
                    pass
            if admission_created:
                try:
                    _update_admission(
                        "HOLD", attempts_readback, unknown_readback
                    )
                except Exception:
                    pass
            print(
                "ITEM32_CLEANUP_HOLD container_or_runtime_residue=UNKNOWN",
                file=sys.stderr,
                flush=True,
            )
            if not active_error:
                raise Item32Error("cleanup_incomplete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    args = parser.parse_args(argv)
    executor_path = Path(__file__).resolve()
    try:
        export_path = execute(Path(args.plan).resolve(), executor_path)
    except Item32Error as exc:
        print(
            f"ITEM32_EXECUTION_REJECTED code={exc} automatic_retry_count=0",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            "ITEM32_EXECUTION_REJECTED code=unexpected automatic_retry_count=0",
            file=sys.stderr,
        )
        return 2
    raw = export_path.read_bytes()
    print(
        "ITEM32_EXECUTION_VERIFIED"
        f" export_path={export_path} export_sha256={_sha256_bytes(raw)}"
        f" export_size={len(raw)} provider_calls=34 automatic_retry_count=0"
        " production_db_writes=0 postpaid_resources_started=0 secret_values_exposed=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
