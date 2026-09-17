#!/usr/bin/env python3
"""Run the fresh, single bounded Item32 Trends observation on API-F.

The collection container receives an isolated SQLite store and the XHS session
only.  It never receives DATABASE_URL.  Separate short-lived probes open an
explicit read-only PostgreSQL transaction before and after the collection.
The two earlier Item32 attempts remain immutable HOLD boundaries and are never
replayed; this executor admits one new identity only after binding both holds.
"""

from __future__ import annotations

import argparse
import base64
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UNIT = "noteai-xhs-trends.service"
SECRET_ENV = Path("/etc/noteai/xhs-trends.env")
WORK_ROOT = Path("/var/lib/noteai/item32-readonly-successor")
EXPORT_ROOT = Path("/home/ecs-assist-user")
RUNTIME_ROOT = Path("/run")
SEALED_ORIGINAL_ROOT = Path("/var/lib/noteai/item32-readonly")
SEALED_ORIGINAL_ADMISSION = SEALED_ORIGINAL_ROOT / "item32-admission.json"
SEALED_DIAGNOSTIC_ROOT = Path("/var/lib/noteai/item32-xhs-diagnostic")
SEALED_DIAGNOSTIC_ADMISSION = SEALED_DIAGNOSTIC_ROOT / "admission.json"
SEALED_DIAGNOSTIC_RESULT = SEALED_DIAGNOSTIC_ROOT / "result.json"
PLAN_SCHEMA = "noteai.item32.readonly_successor_plan.v2"
V5_PLAN_SCHEMA = "noteai.item32.readonly_successor_plan.v3"
V5_WORK_ROOT = Path("/var/lib/noteai/item32-v5-successor-20260916")
V5_SEP17_WORK_ROOT = Path("/var/lib/noteai/item32-v5-successor-20260917")
V5_NETWORK_WORK_ROOT = Path("/var/lib/noteai/item32-v5-network-repair-20260917")
V5_SEP17_FINAL_REF = "deploy/production/evidence/production-item32-v5-hold-final-readback-20260917.json"
V5_SEP17_FINAL_SHA256 = "163eeaca405359bfd20afaf0186133c8be14f71609df41788131d5a3b466d3d1"
V5_NETWORK_D0_REF = "deploy/production/evidence/production-item32-network-repair-d0-20260917.json"
V5_NETWORK_D0_HOST = "/var/lib/noteai/item32-network-repair-20260917/d0.json"
V5_NETWORK_D0_SHA256 = "6ee589052e1a8b2ed36434a2d97c2448964bc82f60589bfd3c8701e9c026ca48"
V5_NETWORK_D1_SHA256 = "2fc87837f1aba434db7df2c35a34a4226794246e13db2988fb34ac0d9ac7336c"
V5_NETWORK_D2_SHA256 = "3cdd2b5cada5935a6fdea2de16036ea650f46025b9434e83974795f208f4d878"
V5_NETWORK_D0M_SHA256 = "092127cf6f5c1c1bc075874f265e141e018a1ff00dce179ee6a354fc1a21a42d"
V5_SESSION_SHA256 = "18f72f26971be0f578342ea7f8ae6336c7ee66ea67f6e7246b2b7d3866d26f6a"
V5_SEP16_PACKAGE_ROOT = Path("/var/lib/noteai/item32-v5-package-20260916-92dad86")
V5_SEP16_FINAL_REF = "deploy/production/evidence/production-item32-v5-hold-final-readback-20260916.json"
V5_SEP16_FINAL_SHA256 = "b7c11b3013849ab1370d96fb36118cc710b02ecb1cd8113f8945ece01b45a4e2"
SEALED_SUCCESSOR_ROOT = Path("/var/lib/noteai/item32-readonly-successor")
V5_CONFIG_SHA256 = "6d5dcf058c5a0990ba7df3103f63e414de69b62b0ec3481c08490d66ae30b703"
V5_MANIFEST_SHA256 = "87b9bf70c7ded691659ca39d3ea2453f9a97dfbdb83c05c44e838c8b0cf417c9"
V5_UPSTREAM_SHA256 = "ede5937cf326c3fe19edbae8e98cecc8dd9b3b5b983a87594f8d262336328fb6"
V5_OVERLAY_NAMES = frozenset({
    "model/spider_xhs_http.py", "model/spider_xhs_v5.py", "model/security_redaction.py",
    "model/hot_keywords.py", "model/scheduler_a.py", "model/vendor/spider_xhs/v5/trends_bridge.js",
})
V5_PHYSICAL_BUDGET = {"initialization": 2, "collection": 34, "total": 36}
V5_NETWORK_CLIENT_PREFLIGHT = """from curl_cffi.const import CurlInfo
client = v.TrendsCurlClient()
try:
    assert client.session.curl_infos == [getattr(CurlInfo, key) for key in (
        'NAMELOOKUP_TIME', 'CONNECT_TIME', 'APPCONNECT_TIME', 'PRETRANSFER_TIME',
        'STARTTRANSFER_TIME', 'TOTAL_TIME')]
finally:
    client.close()
"""
ACTIVE_V5_PLAN: dict[str, Any] | None = None
TERMINAL_SCHEMA = "noteai.item32.xhs_trends_readonly.v2"
HOLD_EVIDENCE_SCHEMA = "noteai.item32.xhs_diagnostic_hold_unknown.v1"
HOLD_EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-item32-xhs-diagnostic-hold-unknown-20260906.json"
)
HOLD_EVIDENCE_SHA256 = (
    "7c77706e1d7b7bf7b7c157162f95e2d8f04152f736b25bf8b636dd7225cf9ed9"
)
EXPECTED_ORIGINAL_ADMISSION_SHA256 = (
    "8b20840ad5f6e5ec44f14086bfe635ff464c2125bfd76b2cb3b377fa2b48bfd8"
)
EXPECTED_ORIGINAL_STORE_SHA256 = (
    "10e01542b261719794bdaf67ebbc355a8d2fe66e7448c516b206ad300f6402f8"
)
EXPECTED_DIAGNOSTIC_ADMISSION_SHA256 = (
    "85d370068016ccf72fda32840a0cb58e99be82efb2dee6112c29967f76652561"
)
EXPECTED_DIAGNOSTIC_RESULT_SHA256 = (
    "14406787e1064a265ab050b9e7d905752f1144c50498b9f9e281f373b8857382"
)
RUNTIME_READBACK_MAX_AGE = timedelta(minutes=15)
SIGNER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 "
    "Safari/537.36 Edg/138.0.0.0"
)
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
BASELINE_SOURCE = "industry_baseline"
SEARCH_RESULT_SOURCES = {"search_phrase", "search_token"}
ENDPOINT_SEQUENCE = ["homefeed"] * 10 + [
    endpoint
    for _ in range(12)
    for endpoint in ("search_recommend", "search_notes")
]
IMAGE_SOURCE_CONTAINER_PATHS = {
    "model/market_timing_worker.py": "/app/model/market_timing_worker.py",
    "model/trends_contract.py": "/app/model/trends_contract.py",
    "model/hot_keywords.py": "/app/model/hot_keywords.py",
}
ADAPTER_SOURCE_REF = "model/spider_xhs_http.py"
ADAPTER_CONTAINER_PATH = "/app/model/spider_xhs_http.py"
# Current-source preparation only: frozen canonical plan/window must be rebound
# explicitly before execution. The original image hashes remain distinct.
RUNTIME_OVERLAY_SHA256 = {'model/spider_xhs_http.py': '360a43f781e55e2c529387e70ef7be3b5f47a716bf6ede56d3daaaefa9b6bea1', 'model/security_redaction.py': 'c5fc02966035a01012a1a35b7005f3a62a72602c042e98dbad707029ca56f451', 'model/hot_keywords.py': '77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d'}
RUNTIME_OVERLAY_CONTAINER_PATHS = {name: "/app/" + name for name in RUNTIME_OVERLAY_SHA256}

SIGNER_ASSET_CONTAINER_PATH = "/app/model/vendor/spider_xhs/xhs_main_260411.js"
EXPECTED_SIGNER_ASSET_SHA256 = (
    "723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d"
)
EXPECTED_IMAGE_SOURCE_SHA256 = {
    "model/market_timing_worker.py": (
        "e89be24bd3d32c8283acf4cba3f6586d2d5dff7c2c113377b743897bd0527978"
    ),
    "model/trends_contract.py": (
        "530820f68b1feb67aba0037d76ff9548ac0e629fea1c9854cc3df2048e2f2ca8"
    ),
    "model/hot_keywords.py": (
        "48073372ef7c490192ff6cff54c326401b14d313d427e705a1a90f9bc17449b4"
    ),
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


_COMMAND_PHASES = frozenset({
    "HOST_COMMAND",
    "UNIT_FRAGMENT_READBACK", "UNIT_STATE_READBACK",
    "FIXED_CONTAINER_READBACK", "TASK_CONTAINER_READBACK",
    "IMAGE_INSPECT", "IMAGE_SOURCE_CHECK", "RUNTIME_OVERLAY_CHECK",
    "DB_BEFORE_PROBE", "DB_AFTER_PROBE",
    "COLLECTION_CREATE", "COLLECTION_INSPECT", "COLLECTION_START",
    "CONTAINER_REMOVE", "CONTAINER_CLEANUP_READBACK",
})
_COMMAND_DIAGNOSTIC_PATTERNS = (
    ("PYTHON_SYNTAX_ERROR_PATTERN", rb"(?m)^(?:SyntaxError|IndentationError):"),
    ("PYTHON_IMPORT_ERROR_PATTERN", rb"(?m)^(?:ModuleNotFoundError|ImportError):"),
    ("PYTHON_PERMISSION_ERROR_PATTERN", rb"(?m)^PermissionError:"),
    ("SQLITE_OPEN_ERROR_PATTERN", rb"(?m)^sqlite3\.OperationalError: unable to open database file"),
    ("SQLITE_READ_ONLY_PATTERN", rb"(?m)^sqlite3\.OperationalError: attempt to write a readonly database"),
    ("READ_ONLY_FILESYSTEM_PATTERN", rb"(?i)read-only file system"),
    ("DOCKER_DAEMON_UNAVAILABLE_PATTERN", rb"(?i)cannot connect to the docker daemon"),
    ("DOCKER_MOUNT_ERROR_PATTERN", rb"(?i)invalid mount config for type"),
)


class Item32CommandError(Item32Error):
    """Original stable error plus fixed diagnostics; never retain command output."""

    def __init__(self, phase: str, returncode: int, category: str):
        super().__init__("command_failed")
        self.diagnostic = {
            "event": "item32_host_command_failed",
            "phase": phase,
            "returncode": returncode,
            # A matched pattern is a diagnostic clue, not an asserted root cause.
            "stderr_category": category,
        }


def _run(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    stderr_to_stdout: bool = False,
    phase: str = "HOST_COMMAND",
) -> subprocess.CompletedProcess[bytes]:
    if phase not in _COMMAND_PHASES:
        raise Item32Error("command_phase")
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raw = completed.stdout if stderr_to_stdout else completed.stderr
        category = next((name for name, pattern in _COMMAND_DIAGNOSTIC_PATTERNS
            if re.search(pattern, raw or b"")), "UNCLASSIFIED")
        error = Item32CommandError(phase, completed.returncode, category)
        # Do not log argv, exception text, paths, modules, URLs or output bytes.
        # Existing outer invocation logging owns persistence and no-replay.
        print(json.dumps(error.diagnostic, sort_keys=True), file=sys.stderr, flush=True)
        raise error
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
    allowed_keys = EXPECTED_ENV_KEYS | ({"NOTEAI_XHS_WEB_SSK_JSON"} if ACTIVE_V5_PLAN is not None else set())
    for row in rows:
        stripped = row.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise Item32Error("secret_shape")
        key, value = stripped.split("=", 1)
        if key in parsed or key not in allowed_keys or (not value and key != "NOTEAI_XHS_WEB_SSK_JSON"):
            raise Item32Error("secret_shape")
        parsed[key] = value
    if not EXPECTED_ENV_KEYS <= set(parsed) or set(parsed) - allowed_keys:
        raise Item32Error("secret_keys")
    try:
        cookies = json.loads(parsed["NOTEAI_XHS_COOKIES_JSON"])
    except (TypeError, ValueError) as exc:
        raise Item32Error("cookie_shape") from exc
    if (not isinstance(cookies, list) or
        (not 2 <= len(cookies) <= 128 if ACTIVE_V5_PLAN is not None else len(cookies) != 2)):
        raise Item32Error("cookie_shape")
    names: set[str] = set()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise Item32Error("cookie_shape")
        name = cookie.get("name")
        value = cookie.get("value")
        if (
            (not isinstance(name, str) or re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is None
             if ACTIVE_V5_PLAN is not None else name not in EXPECTED_COOKIE_NAMES)
            or name in names
            or not isinstance(value, str)
            or not (8 if name in EXPECTED_COOKIE_NAMES else 1) <= len(value) <= 4096
            or any(character in value for character in "\r\n;")
            or cookie.get("domain") != ".xiaohongshu.com"
            or cookie.get("path") != "/"
        ):
            raise Item32Error("cookie_shape")
        names.add(name)
    if not EXPECTED_COOKIE_NAMES <= names or (ACTIVE_V5_PLAN is None and names != EXPECTED_COOKIE_NAMES):
        raise Item32Error("cookie_shape")
    if ACTIVE_V5_PLAN is not None and parsed.get("NOTEAI_XHS_WEB_SSK_JSON"):
        try:
            storage_raw = parsed["NOTEAI_XHS_WEB_SSK_JSON"]
            storage = json.loads(storage_raw)
            if (len(storage_raw) > 4096 or not isinstance(storage, dict) or set(storage) != {"xhs-pc-web"}
                or not isinstance(storage["xhs-pc-web"], str)
                or not 32 <= len(base64.b64decode(storage["xhs-pc-web"], validate=True)) <= 1024):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise Item32Error("signing_storage_shape") from exc
    return parsed


def _plan_window(admission: Any) -> tuple[datetime, datetime, datetime]:
    if not isinstance(admission, dict):
        raise Item32Error("plan_window")
    start = _parse_clock(admission.get("not_before_utc"))
    deadline = _parse_clock(admission.get("dispatch_deadline_utc"))
    finish = _parse_clock(admission.get("must_finish_before_utc"))
    bucket = admission.get("bucket_date_utc")
    if (
        start.isoformat() != admission.get("not_before_utc")
        or deadline.isoformat() != admission.get("dispatch_deadline_utc")
        or finish.isoformat() != admission.get("must_finish_before_utc")
        or bucket != start.date().isoformat()
        or deadline.date() != start.date()
        or not start < deadline < finish
        or finish - deadline < timedelta(minutes=20)
        or finish > start.replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    ):
        raise Item32Error("plan_window")
    return start, deadline, finish


def _approval_scope_sha256(plan: dict[str, Any]) -> str:
    scope = {key: value for key, value in plan.items() if key != "authorization"}
    return _sha256_bytes(json.dumps(
        scope, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def _assert_plan_authorized(plan: dict[str, Any], deadline: datetime) -> None:
    authorization = plan.get("authorization")
    if (
        not isinstance(authorization, dict)
        or set(authorization) != {"status", "confirmed_at_utc", "approved_scope_sha256"}
        or authorization.get("status") != "AUTHORIZED"
    ):
        raise Item32Error("plan_not_authorized")
    confirmed = _parse_clock(authorization.get("confirmed_at_utc"))
    if (
        confirmed.isoformat() != authorization.get("confirmed_at_utc")
        or confirmed > datetime.now(timezone.utc)
        or confirmed >= deadline
        or authorization.get("approved_scope_sha256") != _approval_scope_sha256(plan)
    ):
        raise Item32Error("plan_authorization_binding")


def _load_plan(
    path: Path,
    executor_path: Path,
    adapter_path: Path,
    hold_evidence_path: Path,
) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32Error("plan_shape") from exc
    if not isinstance(plan, dict) or plan.get("schema") not in {PLAN_SCHEMA, V5_PLAN_SCHEMA}:
        raise Item32Error("plan_binding")
    _, deadline, _ = _plan_window(plan.get("admission"))
    if plan["schema"] == V5_PLAN_SCHEMA:
        _prepare_v5_profile(plan, adapter_path, deadline)
    adapter_sha256 = _sha256_bytes(adapter_path.read_bytes())
    if adapter_sha256 != RUNTIME_OVERLAY_SHA256[ADAPTER_SOURCE_REF]:
        raise Item32Error("plan_binding")
    source_sha256 = {
        **EXPECTED_IMAGE_SOURCE_SHA256,
        **RUNTIME_OVERLAY_SHA256,
    }
    expected = {
        "schema": plan["schema"],
        "item": 32,
        "status": "PREPARED_NOT_EXECUTED",
        "readiness_credit": False,
        "authorization": plan.get("authorization"),
        "outer_executor": (
            "tools/execute_item32_readonly_trends_successor.py"
        ),
        "outer_executor_sha256": _sha256_bytes(executor_path.read_bytes()),
        "adapter_overlay_ref": ADAPTER_SOURCE_REF,
        "adapter_overlay_sha256": adapter_sha256,
        "existing_unit_sha256": EXPECTED_UNIT_SHA256,
        "existing_image_config_sha256": EXPECTED_CONFIG_SHA256,
        "existing_registry_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "registry_manifest_provenance": (
            "SEALED_RELEASE_ATTESTATION_PLUS_FRESH_LOCAL_CONFIG_READBACK"
        ),
        "database_readonly_probe_sha256": DB_PROBE_QUERYSET_SHA256,
        "image_source_sha256": EXPECTED_IMAGE_SOURCE_SHA256,
        "source_sha256": source_sha256,
        "browser_binding": ({
            "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
            "upstream_manifest_ref": "model/vendor/spider_xhs/v5/upstream.json",
            "upstream_manifest_sha256": V5_UPSTREAM_SHA256,
            "cold_initialization": True, "first_homefeed_is_gate": True,
        } if plan["schema"] == V5_PLAN_SCHEMA else {
            "user_agent": SIGNER_USER_AGENT,
            "user_agent_sha256": _sha256_bytes(SIGNER_USER_AGENT.encode()),
            "signer_asset_ref": (
                "model/vendor/spider_xhs/xhs_main_260411.js"
            ),
            "signer_asset_sha256": EXPECTED_SIGNER_ASSET_SHA256,
            "exact_match_required": True,
        }),
        "predecessor_closure": {
            "evidence_ref": HOLD_EVIDENCE_REF,
            "evidence_sha256": HOLD_EVIDENCE_SHA256,
            "original": {
                "status": "HOLD",
                "admission_sha256": EXPECTED_ORIGINAL_ADMISSION_SHA256,
                "store_sha256": EXPECTED_ORIGINAL_STORE_SHA256,
                "provider_call_count": 1,
                "outcome_unknown_count": 0,
                "automatic_retry_count": 0,
                "no_replay": True,
            },
            "diagnostic": {
                "status": "HOLD_UNKNOWN",
                "admission_sha256": EXPECTED_DIAGNOSTIC_ADMISSION_SHA256,
                "result_sha256": EXPECTED_DIAGNOSTIC_RESULT_SHA256,
                "provider_call_count": 1,
                "outcome_unknown_count": 1,
                "automatic_retry_count": 0,
                "no_replay": True,
            },
            "cumulative_provider_call_count": 2,
        },
        "admission": {
            "work_root": str(WORK_ROOT),
            "not_before_utc": plan["admission"]["not_before_utc"],
            "bucket_date_utc": plan["admission"]["bucket_date_utc"],
            "dispatch_deadline_utc": plan["admission"]["dispatch_deadline_utc"],
            "must_finish_before_utc": plan["admission"]["must_finish_before_utc"],
            "current_utc_day_used_required": 0,
            "current_utc_day_remaining_required": 34,
            "provider_requests_planned": 34,
        },
        "bounds": {
            "cycles": 1,
            "provider_requests_per_run_max": 34,
            "provider_requests_per_utc_day_max": 34,
            "keywords_max": 90,
            "real_keywords_per_domain_min": 12,
            "domains": 6,
            "automatic_retry": 0,
        },
        "provider_calls_dispatched": 0,
        "cloud_resources_started": 0,
    }
    if plan["schema"] == V5_PLAN_SCHEMA:
        expected.update(runtime_overlay_sha256=dict(RUNTIME_OVERLAY_SHA256),
                        physical_http_budget=V5_PHYSICAL_BUDGET,
                        previous_successor=plan["previous_successor"])
        if _is_sep17_plan(plan) or _is_network_repair_plan(plan):
            expected["previous_v5_successor"] = _sep17_previous_binding(adapter_path.parent.parent)
        if _is_network_repair_plan(plan):
            expected.update(_network_repair_bindings(adapter_path.parent.parent))
    if not isinstance(plan, dict) or _json_bytes(plan) != _json_bytes(expected):
        raise Item32Error("plan_binding")
    _assert_plan_authorized(plan, deadline)
    if _sha256_bytes(hold_evidence_path.read_bytes()) != HOLD_EVIDENCE_SHA256:
        raise Item32Error("hold_evidence_digest")
    return plan, _sha256_bytes(raw)


def _prepare_v5_profile(plan: dict[str, Any], adapter_path: Path, deadline: datetime) -> None:
    """Select only the already-published v5 image and exact authorized overlays."""
    global ACTIVE_V5_PLAN, WORK_ROOT, IMAGE, EXPECTED_CONFIG_SHA256, EXPECTED_MANIFEST_SHA256
    global EXPECTED_IMAGE_SOURCE_SHA256, RUNTIME_OVERLAY_SHA256, RUNTIME_OVERLAY_CONTAINER_PATHS
    _assert_plan_authorized(plan, deadline)
    overlays = plan.get("runtime_overlay_sha256")
    image_sources = plan.get("image_source_sha256")
    previous = plan.get("previous_successor")
    if (plan.get("existing_image_config_sha256") != V5_CONFIG_SHA256
        or plan.get("existing_registry_manifest_sha256") != V5_MANIFEST_SHA256
        or plan.get("physical_http_budget") != V5_PHYSICAL_BUDGET
        or not isinstance(overlays, dict) or set(overlays) != V5_OVERLAY_NAMES
        or not isinstance(image_sources, dict) or set(image_sources) != set(IMAGE_SOURCE_CONTAINER_PATHS)
        or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
               for value in [*overlays.values(), *image_sources.values()])
        or not isinstance(previous, dict) or set(previous) != {"work_root", "files", "provider_call_count", "no_replay"}
        or previous.get("work_root") != str(SEALED_SUCCESSOR_ROOT)
        or type(previous.get("provider_call_count")) is not int
        or previous.get("provider_call_count") != 1 or previous.get("no_replay") is not True
        or not isinstance(previous.get("files"), dict) or len(previous["files"]) != 11):
        raise Item32Error("plan_binding")
    roots = (str(SEALED_SUCCESSOR_ROOT) + "/", "/var/lib/noteai/item32-successor-package-20260915-79e1e35/",
             "/var/lib/noteai/item32-repair-package-20260915-fac5dd0/")
    for name, binding in previous["files"].items():
        if (not isinstance(name, str) or not name.startswith(roots) or ".." in Path(name).parts
            or Path(name).name not in {"dispatch-started.json", "dispatch-child.json", "dispatch-done.json", "dispatch.log",
                                     "item32-admission.json", "worker-receipt.json", "hot_keywords.db"}
            or not isinstance(binding, dict) or set(binding) != {"bytes", "sha256"}
            or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 64 * 1024 * 1024
            or not isinstance(binding["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]) is None):
            raise Item32Error("plan_binding")
    package = adapter_path.parent.parent
    if _is_network_repair_plan(plan):
        bindings = _network_repair_bindings(package)
        if (any(_json_bytes(plan.get(key)) != _json_bytes(value) for key, value in bindings.items())
            or _json_bytes(plan.get("previous_v5_successor")) != _json_bytes(_sep17_previous_binding(package))
            or _parse_clock(plan["admission"]["not_before_utc"]) < _parse_clock(bindings["network_repair_preflight"]["diagnostics"]["d2"]["finished_at_utc"])
            or _parse_clock(plan["authorization"]["confirmed_at_utc"]) <= _parse_clock("2026-09-17T01:06:56.372948+00:00")):
            raise Item32Error("plan_binding")
    elif _is_sep17_plan(plan):
        expected_window = ("2026-09-17T01:00:00+00:00", "2026-09-17T01:40:00+00:00",
                           "2026-09-17T02:00:00+00:00")
        if (tuple(plan["admission"].get(key) for key in
                  ("not_before_utc", "dispatch_deadline_utc", "must_finish_before_utc")) != expected_window
            or plan["admission"].get("bucket_date_utc") != "2026-09-17"
            or _json_bytes(plan.get("previous_v5_successor")) != _json_bytes(_sep17_previous_binding(package))):
            raise Item32Error("plan_binding")
    elif "previous_v5_successor" in plan:
        raise Item32Error("plan_binding")
    for name, digest in overlays.items():
        if _sha256_bytes((package / name).read_bytes()) != digest:
            raise Item32Error("runtime_overlay_source_binding")
    ACTIVE_V5_PLAN = plan
    WORK_ROOT = V5_NETWORK_WORK_ROOT if _is_network_repair_plan(plan) else V5_SEP17_WORK_ROOT if _is_sep17_plan(plan) else V5_WORK_ROOT
    EXPECTED_CONFIG_SHA256, EXPECTED_MANIFEST_SHA256 = V5_CONFIG_SHA256, V5_MANIFEST_SHA256
    IMAGE = "sha256:" + V5_CONFIG_SHA256
    EXPECTED_IMAGE_SOURCE_SHA256 = dict(image_sources)
    RUNTIME_OVERLAY_SHA256 = dict(overlays)
    RUNTIME_OVERLAY_CONTAINER_PATHS = {name: "/app/" + name for name in overlays}


def _is_sep17_plan(plan: dict[str, Any] | None) -> bool:
    return (isinstance(plan, dict) and plan.get("schema") == V5_PLAN_SCHEMA
            and isinstance(plan.get("admission"), dict)
            and plan["admission"].get("work_root") == str(V5_SEP17_WORK_ROOT))


def _is_network_repair_plan(plan: dict[str, Any] | None) -> bool:
    return (isinstance(plan, dict) and plan.get("schema") == V5_PLAN_SCHEMA
            and isinstance(plan.get("admission"), dict)
            and plan["admission"].get("work_root") == str(V5_NETWORK_WORK_ROOT))


def _network_diagnostics_bindings(package: Path) -> dict[str, Any]:
    """Completed transport and one DSL-shape diagnostic precede the new formal run."""
    result, values = {}, {}
    for name in ("d1", "d2"):
        ref = f"deploy/production/evidence/production-item32-network-repair-{name}-20260917.json"
        raw = (package / ref).read_bytes()
        if not 0 < len(raw) <= 65536:
            raise Item32Error("network_diagnostic_binding")
        value = json.loads(raw); values[name] = value
        if not isinstance(value, dict):
            raise Item32Error("network_diagnostic_binding")
        result[name] = {"ref": ref, "host_ref": f"/var/lib/noteai/item32-network-repair-20260917/{name}/result.json",
                        "bytes": len(raw), "sha256": _sha256_bytes(raw), "finished_at_utc": value["finished_at_utc"]}
    d1, d2 = values["d1"], values["d2"]
    delivery = d2.get("result")
    worker = delivery.get("worker") if isinstance(delivery, dict) else None
    required = {"schema": "noteai.item32.d2_dsl_once.v1", "state": "D2_COMPLETED",
        "d0_sha256": V5_NETWORK_D0_SHA256, "d1_result_sha256": V5_NETWORK_D1_SHA256,
        "d0m_result_sha256": V5_NETWORK_D0M_SHA256, "container_removed": True, "bindings_unchanged": True,
        "automatic_retry_count": 0, "maximum_dsl_get": 1, "session_requests": 0, "collection_requests": 0,
        "database_operations": 0, "business_credentials_loaded": False, "readiness_credit": False,
        "second_dsl_automatically_allowed": False}
    worker_required = {"schema": "noteai.item32.d2_dsl_worker.v1", "state": "DSL_SHAPE_VERIFIED",
        "phase": "response_parse", "http_dispatches_observed": 1, "automatic_retry_count": 0,
        "response_headers_state": "received", "response_body_state": "complete", "dsl_shape_valid": True,
        "body_limit_exceeded": False, "error_type": "none", "business_credentials_loaded": False,
        "response_body_saved": False, "response_headers_saved": False, "dsl_value_saved": False}
    if (result["d1"]["bytes"] != 1999 or result["d1"]["sha256"] != V5_NETWORK_D1_SHA256
        or result["d2"]["bytes"] != 1407 or result["d2"]["sha256"] != V5_NETWORK_D2_SHA256
        or d1.get("state") != "D1_COMPLETED" or d1.get("container_removed") is not True
        or d1.get("bindings_unchanged") is not True or type(d1.get("http_requests")) is not int or d1["http_requests"] != 0
        or set(d1.get("environments", {})) != {"host", "container"}
        or any(env.get("state") != "PASSED" or env.get("local_process_reaped") is not True
               or env.get("observation_complete") is not True for env in d1["environments"].values())
        or any(type(d2.get(key)) is not type(value) or d2[key] != value for key, value in required.items())
        or not isinstance(delivery, dict) or delivery.get("local_process_reaped") is not True
        or not isinstance(worker, dict)
        or any(type(worker.get(key)) is not type(value) or worker[key] != value for key, value in worker_required.items())
        or type(worker.get("http_status")) is not int or not 200 <= worker["http_status"] < 300
        or not _parse_clock(d1["finished_at_utc"]) <= _parse_clock(d2["finished_at_utc"])):
        raise Item32Error("network_diagnostic_binding")
    return result


def _network_repair_bindings(package: Path) -> dict[str, Any]:
    """Bind original initialization UNKNOWN independently of the zero collection ledger."""
    raw = (package / V5_SEP17_FINAL_REF).read_bytes()
    if len(raw) != 6794 or _sha256_bytes(raw) != V5_SEP17_FINAL_SHA256:
        raise Item32Error("predecessor_final_seal")
    seal = json.loads(raw)
    d0_raw = (package / V5_NETWORK_D0_REF).read_bytes()
    if len(d0_raw) != 2895 or _sha256_bytes(d0_raw) != V5_NETWORK_D0_SHA256:
        raise Item32Error("network_preflight_binding")
    d0 = json.loads(d0_raw)
    required = {"schema": "noteai.item32.network_repair_d0.v1", "state": "D0_READONLY_PASSED",
        "host": "noteai-api-f", "source_revision": "84f2e6e6ff97e0559335f3ebadfdccabb9ccd280",
        "locks_available": 5, "predecessor_files_verified": 20, "sep17_files_verified": 10,
        "task_containers_absent": True, "no_in_flight": True, "unit_sha256": EXPECTED_UNIT_SHA256,
        "session_env_sha256": V5_SESSION_SHA256, "sep17_final_readback_sha256": V5_SEP17_FINAL_SHA256,
        "new_provider_requests": 0, "database_operations": 0, "container_starts": 0,
        "original_files_modified": False, "raw_log_returned": False, "secret_values_output": False, "errors": []}
    if (not isinstance(d0, dict) or not 0 < len(d0_raw) <= 65536
        or any(type(d0.get(key)) is not type(value) or d0[key] != value for key, value in required.items())
        or not _parse_clock(seal["observed_utc"]) <= _parse_clock(d0["observed_at_utc"]) <= _parse_clock(d0["finished_at_utc"])):
        raise Item32Error("network_preflight_binding")
    return {"previous_v5_initialization_hold": {
        "work_root": str(V5_SEP17_WORK_ROOT), "package_root": "/var/lib/noteai/item32-v5-package-20260917-84f2e6e",
        "status": "HOLD_INITIALIZATION_NETWORK_UNKNOWN_RESTORED", "call_date_utc": "2026-09-17",
        "collection_admissions": 0, "collection_outcome_unknown_count": 0,
        "initialization_count": 1, "initialization_outcome_unknown_count": 1, "physical_http_count": 1,
        "automatic_retry_count": 0, "no_replay": True, "files": seal["files"],
        "final_readback": {"ref": V5_SEP17_FINAL_REF, "host_ref": str(V5_SEP17_WORK_ROOT / "hold-final-readback.json"),
                           "bytes": 6794, "sha256": V5_SEP17_FINAL_SHA256}},
        "network_repair_preflight": {"ref": V5_NETWORK_D0_REF, "host_ref": V5_NETWORK_D0_HOST,
            "bytes": len(d0_raw), "sha256": _sha256_bytes(d0_raw), "finished_at_utc": d0["finished_at_utc"],
            "diagnostics": _network_diagnostics_bindings(package)}}


def _sep17_previous_binding(package: Path) -> dict[str, Any]:
    raw = (package / V5_SEP16_FINAL_REF).read_bytes()
    if len(raw) != 2386 or _sha256_bytes(raw) != V5_SEP16_FINAL_SHA256:
        raise Item32Error("predecessor_final_seal")
    seal = json.loads(raw)
    return {"work_root": str(V5_WORK_ROOT), "package_root": str(V5_SEP16_PACKAGE_ROOT),
            "status": "HOLD", "call_date_utc": "2026-09-16", "collection_admissions": 11,
            "initialization_count": 2, "physical_http_count": 13, "outcome_unknown_count": 0,
            "automatic_retry_count": 0, "no_replay": True, "files": seal["files"],
            "final_readback": {"ref": V5_SEP16_FINAL_REF,
                "host_ref": str(V5_WORK_ROOT / "hold-final-readback.json"),
                "bytes": 2386, "sha256": V5_SEP16_FINAL_SHA256}}


def _read_regular_file(
    path: Path,
    *,
    max_size: int,
    root_only: bool,
) -> bytes:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= max_size
        or (root_only and stat.S_IMODE(metadata.st_mode) != 0o600)
        or (root_only and (metadata.st_uid != 0 or metadata.st_gid != 0))
    ):
        raise Item32Error("predecessor_metadata")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = b""
        while True:
            chunk = os.read(descriptor, 8192)
            if not chunk:
                break
            raw += chunk
            if len(raw) > max_size:
                raise Item32Error("predecessor_size")
        return raw
    finally:
        os.close(descriptor)


def _acquire_predecessor_locks() -> list[int]:
    descriptors: list[int] = []
    try:
        roots = (SEALED_ORIGINAL_ROOT, SEALED_DIAGNOSTIC_ROOT)
        if ACTIVE_V5_PLAN is not None:
            roots += (SEALED_SUCCESSOR_ROOT,)
        if _is_sep17_plan(ACTIVE_V5_PLAN) or _is_network_repair_plan(ACTIVE_V5_PLAN):
            roots += (V5_WORK_ROOT,)
        if _is_network_repair_plan(ACTIVE_V5_PLAN):
            roots += (V5_SEP17_WORK_ROOT,)
        for root in roots:
            descriptor = os.open(
                root / "executor.lock", os.O_RDONLY | os.O_NOFOLLOW
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
                raise Item32Error("predecessor_lock_metadata")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(descriptor)
                raise Item32Error("predecessor_active") from exc
            descriptors.append(descriptor)
        return descriptors
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


def _verify_predecessors(
    plan: dict[str, Any],
    hold_evidence_path: Path,
) -> dict[str, Any]:
    closure_raw = hold_evidence_path.read_bytes()
    if _sha256_bytes(closure_raw) != HOLD_EVIDENCE_SHA256:
        raise Item32Error("hold_evidence_digest")
    try:
        closure = json.loads(closure_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32Error("hold_evidence_shape") from exc
    retained = closure.get("retained_audit_boundary")
    diagnostic = closure.get("diagnostic_attempt")
    sealed = closure.get("sealed_prior_attempt")
    counters = closure.get("counters")
    acceptance = closure.get("acceptance")
    if (
        closure.get("schema") != HOLD_EVIDENCE_SCHEMA
        or closure.get("status") != "DIAGNOSTIC_HOLD_UNKNOWN_NO_CREDIT"
        or closure.get("readiness_credit") is not False
        or closure.get("classification") != "UNKNOWN_HOLD"
        or closure.get("admission_status") != "HOLD_UNKNOWN"
        or closure.get("no_replay") is not True
        or not isinstance(retained, dict)
        or retained.get("admission_sha256")
        != EXPECTED_DIAGNOSTIC_ADMISSION_SHA256
        or retained.get("result_sha256") != EXPECTED_DIAGNOSTIC_RESULT_SHA256
        or retained.get("admission_bound_result_sha256")
        != EXPECTED_DIAGNOSTIC_RESULT_SHA256
        or retained.get("admission_result_sha256_match") is not True
        or not isinstance(diagnostic, dict)
        or diagnostic.get("provider_call_count") != 1
        or diagnostic.get("outcome_unknown_count") != 1
        or diagnostic.get("automatic_retry_count") != 0
        or diagnostic.get("response_received") is not False
        or not isinstance(sealed, dict)
        or sealed.get("admission_sha256")
        != EXPECTED_ORIGINAL_ADMISSION_SHA256
        or sealed.get("isolated_store_sha256")
        != EXPECTED_ORIGINAL_STORE_SHA256
        or sealed.get("provider_call_count") != 1
        or sealed.get("outcome_unknown_count") != 0
        or sealed.get("automatic_retry_count") != 0
        or sealed.get("no_replay") is not True
        or not isinstance(counters, dict)
        or counters.get("cumulative_provider_call_count") != 2
        or counters.get("automatic_retry_count") != 0
        or counters.get("production_database_writes") != 0
        or not isinstance(acceptance, dict)
        or acceptance.get("item32_credit") is not False
        or acceptance.get("further_xhs_provider_actions_authorized") is not False
    ):
        raise Item32Error("hold_evidence_shape")

    original_raw = _read_regular_file(
        SEALED_ORIGINAL_ADMISSION, max_size=16384, root_only=True
    )
    diagnostic_admission_raw = _read_regular_file(
        SEALED_DIAGNOSTIC_ADMISSION, max_size=32768, root_only=True
    )
    diagnostic_result_raw = _read_regular_file(
        SEALED_DIAGNOSTIC_RESULT, max_size=131072, root_only=True
    )
    if (
        _sha256_bytes(original_raw) != EXPECTED_ORIGINAL_ADMISSION_SHA256
        or _sha256_bytes(diagnostic_admission_raw)
        != EXPECTED_DIAGNOSTIC_ADMISSION_SHA256
        or _sha256_bytes(diagnostic_result_raw)
        != EXPECTED_DIAGNOSTIC_RESULT_SHA256
    ):
        raise Item32Error("predecessor_digest")
    try:
        original_admission = json.loads(original_raw.decode("utf-8"))
        diagnostic_admission = json.loads(
            diagnostic_admission_raw.decode("utf-8")
        )
        diagnostic_result = json.loads(diagnostic_result_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32Error("predecessor_shape") from exc
    diagnostic_result_detail = diagnostic_result.get("result")
    if (
        original_admission.get("status") != "HOLD"
        or original_admission.get("provider_calls") != 1
        or original_admission.get("outcome_unknown_count") != 0
        or original_admission.get("automatic_retry_count") != 0
        or diagnostic_admission.get("status") != "HOLD_UNKNOWN"
        or diagnostic_admission.get("provider_call_count") != 1
        or diagnostic_admission.get("outcome_unknown_count") != 1
        or diagnostic_admission.get("automatic_retry_count") != 0
        or diagnostic_admission.get("no_replay") is not True
        or diagnostic_admission.get("result_sha256")
        != EXPECTED_DIAGNOSTIC_RESULT_SHA256
        or diagnostic_result.get("schema")
        != "noteai.item32.xhs_diagnostic_result.v1"
        or diagnostic_result.get("status")
        != "DIAGNOSTIC_HOLD_UNKNOWN_NO_CREDIT"
        or diagnostic_result.get("readiness_credit") is not False
        or not isinstance(diagnostic_result_detail, dict)
        or diagnostic_result_detail.get("classification") != "UNKNOWN_HOLD"
        or diagnostic_result_detail.get("provider_call_count") != 1
        or diagnostic_result_detail.get("outcome_unknown_count") != 1
        or diagnostic_result_detail.get("automatic_retry_count") != 0
    ):
        raise Item32Error("predecessor_shape")

    run_directories = sorted(SEALED_ORIGINAL_ROOT.glob("run-*"))
    if len(run_directories) != 1:
        raise Item32Error("predecessor_store_count")
    original_database = run_directories[0] / "task-store" / "hot_keywords.db"
    original_store_raw = _read_regular_file(
        original_database, max_size=64 * 1024 * 1024, root_only=False
    )
    if _sha256_bytes(original_store_raw) != EXPECTED_ORIGINAL_STORE_SHA256:
        raise Item32Error("predecessor_store_digest")
    try:
        connection = sqlite3.connect(
            f"file:{original_database}?mode=ro&immutable=1", uri=True
        )
        try:
            rows = connection.execute(
                "SELECT admitted_at,status FROM xhs_trends_provider_attempts "
                "ORDER BY ordinal"
            ).fetchall()
            unresolved = int(
                connection.execute(
                    "SELECT COUNT(*) FROM xhs_trends_provider_attempts "
                    "WHERE status IN ('admitted','outcome_unknown')"
                ).fetchone()[0]
            )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise Item32Error("predecessor_store_read") from exc
    if len(rows) != 1 or rows[0][1] != "failed" or unresolved != 0:
        raise Item32Error("predecessor_store_shape")
    original_call_clock = _parse_clock(rows[0][0])
    diagnostic_call_clock = _parse_clock(diagnostic["observed_at"])
    result = {
        "closure_sha256": HOLD_EVIDENCE_SHA256,
        "original_admission_sha256": EXPECTED_ORIGINAL_ADMISSION_SHA256,
        "original_store_sha256": EXPECTED_ORIGINAL_STORE_SHA256,
        "diagnostic_admission_sha256": EXPECTED_DIAGNOSTIC_ADMISSION_SHA256,
        "diagnostic_result_sha256": EXPECTED_DIAGNOSTIC_RESULT_SHA256,
        "call_dates": [
            original_call_clock.date().isoformat(),
            diagnostic_call_clock.date().isoformat(),
        ],
    }
    if ACTIVE_V5_PLAN is not None:
        previous = _verify_v5_previous(plan["previous_successor"])
        result["previous_successor"] = previous
        result["call_dates"].append(previous["call_date_utc"])
    if _is_sep17_plan(plan) or _is_network_repair_plan(plan):
        previous, call_dates = _verify_sep16_v5_previous(plan["previous_v5_successor"])
        result["previous_v5_successor"] = previous
        result["call_dates"].extend(call_dates)
    if _is_network_repair_plan(plan):
        previous, preflight = _verify_sep17_initialization_hold(plan)
        result["previous_v5_initialization_hold"] = previous
        result["network_repair_preflight"] = preflight
    return result


def _verify_sep17_initialization_hold(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    binding, d0 = plan["previous_v5_initialization_hold"], plan["network_repair_preflight"]
    seal_raw = _read_regular_file(Path(binding["final_readback"]["host_ref"]), max_size=6794, root_only=True)
    if len(seal_raw) != 6794 or _sha256_bytes(seal_raw) != V5_SEP17_FINAL_SHA256:
        raise Item32Error("predecessor_final_seal")
    seal = json.loads(seal_raw)
    originals = {}
    for name, expected in binding["files"].items():
        path = Path(name)
        raw = _read_regular_file(path, max_size=64 * 1024 * 1024, root_only=path.name != "hot_keywords.db")
        if (len(raw) != expected["bytes"] or _sha256_bytes(raw) != expected["sha256"]
            or oct(stat.S_IMODE(os.lstat(path).st_mode)) != expected["mode"]):
            raise Item32Error("predecessor_digest")
        originals[name] = raw
    run = V5_SEP17_WORK_ROOT / seal["admission"]["run_directory_name"]
    if (json.loads(originals[str(V5_SEP17_WORK_ROOT / "item32-admission.json")]) != seal["admission"]
        or json.loads(originals[str(run / "worker-receipt.json")]) != seal["worker_receipt"]
        or any(json.loads(originals[str(run / f"database-{phase}-probe.json")]) != seal["database_probes"][phase]
               for phase in ("before", "after"))):
        raise Item32Error("predecessor_shape")
    connection = sqlite3.connect(f"file:{run / 'task-store/hot_keywords.db'}?mode=ro&immutable=1", uri=True)
    try:
        count = connection.execute("SELECT COUNT(*) FROM xhs_trends_provider_attempts").fetchone()[0]
    finally:
        connection.close()
    if count != 0:
        raise Item32Error("predecessor_store_shape")
    raw = _read_regular_file(Path(d0["host_ref"]), max_size=65536, root_only=True)
    if (len(raw) != d0["bytes"] or _sha256_bytes(raw) != d0["sha256"]
        or _sha256_bytes(_read_regular_file(SECRET_ENV, max_size=65536, root_only=True)) != V5_SESSION_SHA256):
        raise Item32Error("network_preflight_binding")
    for evidence in d0["diagnostics"].values():
        raw = _read_regular_file(Path(evidence["host_ref"]), max_size=65536, root_only=True)
        if len(raw) != evidence["bytes"] or _sha256_bytes(raw) != evidence["sha256"]:
            raise Item32Error("network_diagnostic_binding")
    return ({**binding, "host_final_readback_verified": True, "database_readonly_probes_verified": True},
            {**d0, "host_readback_verified": True})


def _verify_v5_previous(binding: dict[str, Any]) -> dict[str, Any]:
    admission_path = SEALED_SUCCESSOR_ROOT / "item32-admission.json"
    admission = json.loads(_read_regular_file(admission_path, max_size=65536, root_only=True))
    run = admission.get("run_directory_name")
    if (not isinstance(run, str) or re.fullmatch(r"run-[a-zA-Z0-9_-]{1,64}", run) is None
        or admission.get("status") != "HOLD" or admission.get("provider_calls") != 1
        or admission.get("outcome_unknown_count") != 0 or admission.get("automatic_retry_count") != 0
        or admission.get("no_replay") is not True):
        raise Item32Error("predecessor_shape")
    expected_paths = {str(admission_path), str(SEALED_SUCCESSOR_ROOT / run / "worker-receipt.json"),
                      str(SEALED_SUCCESSOR_ROOT / run / "task-store/hot_keywords.db")}
    for stage in ("item32-successor-package-20260915-79e1e35", "item32-repair-package-20260915-fac5dd0"):
        expected_paths.update(f"/var/lib/noteai/{stage}/{name}" for name in
                              ("dispatch-started.json", "dispatch-child.json", "dispatch-done.json", "dispatch.log"))
    if set(binding["files"]) != expected_paths:
        raise Item32Error("predecessor_shape")
    for name, expected in binding["files"].items():
        raw = _read_regular_file(Path(name), max_size=64 * 1024 * 1024, root_only=not name.endswith("/hot_keywords.db"))
        if len(raw) != expected["bytes"] or _sha256_bytes(raw) != expected["sha256"]:
            raise Item32Error("predecessor_digest")
    database = SEALED_SUCCESSOR_ROOT / run / "task-store/hot_keywords.db"
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute("SELECT admitted_at,status FROM xhs_trends_provider_attempts ORDER BY ordinal").fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or rows[0][1] != "failed":
        raise Item32Error("predecessor_store_shape")
    return {"files_sha256": _sha256_bytes(_json_bytes(binding["files"])), "provider_call_count": 1,
            "call_date_utc": _parse_clock(rows[0][0]).date().isoformat(), "no_replay": True}


def _verify_sep16_v5_previous(binding: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Read the one sealed Sep16 HOLD; never repair or replay its ledger."""
    seal = _read_regular_file(Path(binding["final_readback"]["host_ref"]), max_size=65536, root_only=True)
    if len(seal) != 2386 or _sha256_bytes(seal) != V5_SEP16_FINAL_SHA256:
        raise Item32Error("predecessor_final_seal")
    originals = {}
    for name, expected in binding["files"].items():
        path = Path(name)
        raw = _read_regular_file(path, max_size=64 * 1024 * 1024, root_only=path.name != "hot_keywords.db")
        if (len(raw) != expected["bytes"] or _sha256_bytes(raw) != expected["sha256"]
            or oct(stat.S_IMODE(os.lstat(path).st_mode)) != expected["mode"]):
            raise Item32Error("predecessor_digest")
        originals[name] = raw
    admission = json.loads(originals[str(V5_WORK_ROOT / "item32-admission.json")])
    run_name = admission.get("run_directory_name")
    if (not isinstance(run_name, str) or re.fullmatch(r"run-[A-Za-z0-9_-]{1,64}", run_name) is None
        or admission.get("status") != "HOLD" or type(admission.get("provider_calls")) is not int
        or admission["provider_calls"] != 11 or type(admission.get("outcome_unknown_count")) is not int
        or admission["outcome_unknown_count"] != 0 or type(admission.get("automatic_retry_count")) is not int
        or admission["automatic_retry_count"] != 0 or admission.get("no_replay") is not True
        or admission.get("budget", {}).get("bucket_date") != "2026-09-16"
        or admission.get("physical_http_budget") != V5_PHYSICAL_BUDGET):
        raise Item32Error("predecessor_shape")
    run = V5_WORK_ROOT / run_name
    database = run / "task-store/hot_keywords.db"
    if str(database) not in originals:
        raise Item32Error("predecessor_shape")
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute("SELECT ordinal,endpoint,status,admitted_at,admitted_date,completed_at "
                                  "FROM xhs_trends_provider_attempts ORDER BY ordinal").fetchall()
    finally:
        connection.close()
    if (len(rows) != 11 or any(row[0] != index + 1 or row[1] != ENDPOINT_SEQUENCE[index]
        or row[2] != ("succeeded" if index < 10 else "failed") or row[4] != "2026-09-16"
        or _parse_clock(row[3]).date().isoformat() != "2026-09-16"
        or _parse_clock(row[5]).date().isoformat() != "2026-09-16"
        or _parse_clock(row[5]) < _parse_clock(row[3]) for index, row in enumerate(rows))):
        raise Item32Error("predecessor_store_shape")
    receipt = json.loads(originals[str(run / "worker-receipt.json")])
    expected_summary = {"initialization_dispatches_observed": 2,
        "initialization_request_counts": {"dsl": 1, "session": 1}, "collection_dispatches_observed": 11,
        "response_events_observed": 13, "unknown_events_observed": 0,
        "unresolved_dispatches_observed": 0, "invalid_observations": 0, "observation_complete": True}
    observations = receipt.get("physical_http_observations")
    if (type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 1
        or receipt.get("secret_values_recorded") is not False
        or _json_bytes(receipt.get("physical_http_summary")) != _json_bytes(expected_summary)
        or not isinstance(observations, list) or len(observations) != 26):
        raise Item32Error("predecessor_worker_shape")
    first_http, last_http = None, None
    for index, kind in enumerate(["dsl", "session", *ENDPOINT_SEQUENCE[:11]]):
        dispatch, response = observations[index * 2:index * 2 + 2]
        if (dispatch.get("phase") != "dispatch" or response.get("phase") != "response"
            or any(item.get("request_kind") != kind or type(item.get("sequence")) is not int
                   or item["sequence"] != index + 1 for item in (dispatch, response))):
            raise Item32Error("predecessor_worker_shape")
        first, last = _parse_clock(dispatch.get("at")), _parse_clock(response.get("at"))
        if (first.date().isoformat() != "2026-09-16" or last.date().isoformat() != "2026-09-16"
            or first > last or last_http is not None and first < last_http):
            raise Item32Error("predecessor_worker_shape")
        first_http = first if first_http is None else first_http
        last_http = last
        if index >= 2 and not _parse_clock(rows[index - 2][3]) <= first <= last <= _parse_clock(rows[index - 2][5]):
            raise Item32Error("predecessor_store_shape")
    probes = [json.loads(originals[str(run / f"database-{phase}-probe.json")]) for phase in ("before", "after")]
    for probe in probes:
        if (any(type(probe.get(key)) is not int or probe[key] != 0 for key in
                ("write_count", "tuple_write_count", "active_or_manual_count", "session_blocked_count", "today_attempt_count"))
            or probe.get("server_enforced_read_only") is not True or probe.get("write_tables") != []
            or probe.get("xid_assigned") is not False or probe.get("transaction_rolled_back") is not True
            or probe.get("secret_values_recorded") is not False
            or probe.get("readback_query_sha256") != DB_PROBE_QUERYSET_SHA256
            or not isinstance(probe.get("session_identity_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", probe["session_identity_sha256"]) is None):
            raise Item32Error("predecessor_database_proof")
    before, after = map(lambda value: _parse_clock(value["observed_at"]), probes)
    if (probes[0]["session_identity_sha256"] != probes[1]["session_identity_sha256"]
        or before.date().isoformat() != "2026-09-16" or after.date().isoformat() != "2026-09-16"
        or not before <= first_http <= last_http <= after <= _parse_clock(json.loads(seal)["at"])):
        raise Item32Error("predecessor_database_proof")
    return ({**binding, "host_final_readback_verified": True, "database_readonly_probes_verified": True},
            [_parse_clock(row[3]).date().isoformat() for row in rows])


def _admission_budget(
    plan: dict[str, Any],
    predecessor: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    not_before = _parse_clock(plan["admission"]["not_before_utc"])
    dispatch_deadline = _parse_clock(
        plan["admission"]["dispatch_deadline_utc"]
    )
    bucket = plan["admission"]["bucket_date_utc"]
    if (
        current < not_before
        or current >= dispatch_deadline
        or current.date().isoformat() != bucket
    ):
        raise Item32Error("utc_budget_not_available")
    prior_used = sum(
        1 for value in predecessor["call_dates"] if value == bucket
    )
    if prior_used != 0 or ((_is_sep17_plan(plan) or _is_network_repair_plan(plan)) and any(value >= bucket for value in predecessor["call_dates"])):
        raise Item32Error("utc_budget_not_available")
    return {
        "bucket_date": bucket,
        "used_before": 0,
        "remaining_before": 34,
        "planned": 34,
        "limit": 34,
    }


def _assert_dispatch_window(
    plan: dict[str, Any],
    budget: dict[str, Any],
    runtime_readback: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    runtime_at = _parse_clock(runtime_readback["observed_at"])
    admission = plan["admission"]
    if (
        budget["bucket_date"] != admission["bucket_date_utc"]
        or current.date().isoformat() != budget["bucket_date"]
        or current < _parse_clock(admission["not_before_utc"])
        or current >= _parse_clock(admission["dispatch_deadline_utc"])
        or current >= _parse_clock(admission["must_finish_before_utc"])
        or runtime_at > current
        or current - runtime_at > RUNTIME_READBACK_MAX_AGE
    ):
        raise Item32Error("dispatch_window")


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


def _create_admission(
    run_identity_sha256: str,
    *,
    plan_sha256: str,
    predecessor: dict[str, Any],
    budget: dict[str, Any],
    run_directory_name: str | None = None,
) -> None:
    if run_directory_name is not None and re.fullmatch(
        r"run-[a-zA-Z0-9_-]{1,64}", run_directory_name
    ) is None:
        raise Item32Error("recovery_run_identity")
    payload = _json_bytes(
        {
            "schema": "noteai.item32.successor_admission.v1",
            "status": "DISPATCHED",
            "created_at": _utc_now(),
            "run_identity_sha256": run_identity_sha256,
            "plan_sha256": plan_sha256,
            "predecessor_closure_sha256": predecessor["closure_sha256"],
            "budget": budget,
            "automatic_retry_count": 0,
            "no_replay": True,
            "run_directory_name": run_directory_name,
            **({"physical_http_budget": dict(V5_PHYSICAL_BUDGET)} if ACTIVE_V5_PLAN is not None else {}),
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


def _update_admission(
    status: str,
    provider_calls: int | None,
    unknown_count: int | None,
) -> None:
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
    if (
        original.get("schema") != "noteai.item32.successor_admission.v1"
        or original.get("status") not in {"DISPATCHED", "SUCCEEDED"}
        or (
            original.get("status") == "SUCCEEDED" and status != "HOLD"
        )
        or original.get("automatic_retry_count") != 0
        or original.get("no_replay") is not True
        or original.get("predecessor_closure_sha256")
        != HOLD_EVIDENCE_SHA256
    ):
        raise Item32Error("admission_shape")
    def normalized_count(value: int | None) -> int | str:
        if value is None:
            return "UNKNOWN"
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Item32Error("admission_count")
        return value

    original.update(
        {
            "status": status,
            "updated_at": _utc_now(),
            "provider_calls": normalized_count(provider_calls),
            "outcome_unknown_count": normalized_count(unknown_count),
        }
    )
    _atomic_write(path, _json_bytes(original), 0o600)


def _remove_container(name: str) -> None:
    if not name:
        return
    _run(["docker", "rm", "-f", name], check=False, phase="CONTAINER_REMOVE")
    remaining = _run(
        ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
        phase="CONTAINER_CLEANUP_READBACK",
    ).stdout.strip()
    if remaining:
        raise Item32Error("container_cleanup")


def _remove_registered_container(
    registry: dict[str, str],
    name: str,
) -> None:
    _remove_container(name)
    registry.pop(name, None)


def _cleanup_registered_containers(registry: dict[str, str]) -> None:
    failed = False
    for name in tuple(registry):
        try:
            _remove_registered_container(registry, name)
        except Exception:
            failed = True
    try:
        remaining = _run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.noteai.task=item32-readonly-successor",
            ],
            phase="TASK_CONTAINER_READBACK",
        ).stdout.strip()
    except Exception:
        remaining = b"UNKNOWN"
    if registry or remaining or failed:
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
        ],
        phase="UNIT_STATE_READBACK",
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
        ["docker", "ps", "-aq", "--filter", "name=^/noteai-xhs-trends$"],
        phase="FIXED_CONTAINER_READBACK",
    ).stdout.strip():
        raise Item32Error("trends_container_present")


def _assert_adapter_source(path: Path) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= 1024 * 1024
    ):
        raise Item32Error("adapter_source_metadata")


def _runtime_overlay_paths(adapter_path: Path) -> dict[str, Path]:
    if ACTIVE_V5_PLAN is not None:
        return {name: adapter_path.parent.parent / name for name in RUNTIME_OVERLAY_SHA256}
    return {name: adapter_path if name == ADAPTER_SOURCE_REF else adapter_path.parent / Path(name).name
            for name in RUNTIME_OVERLAY_SHA256}


def _assert_runtime_overlay_sources(adapter_path: Path) -> None:
    for name, path in _runtime_overlay_paths(adapter_path).items():
        _assert_adapter_source(path)
        if _sha256_bytes(path.read_bytes()) != RUNTIME_OVERLAY_SHA256[name]:
            raise Item32Error("runtime_overlay_source_binding")


def _runtime_overlay_mounts(adapter_path: Path) -> list[str]:
    return [arg for name, path in _runtime_overlay_paths(adapter_path).items()
            for arg in ("--mount", f"type=bind,src={path},dst={RUNTIME_OVERLAY_CONTAINER_PATHS[name]},readonly")]


def _preflight_host(
    plan: dict[str, Any], adapter_path: Path
) -> dict[str, Any]:
    _validated_export_account()
    _assert_runtime_overlay_sources(adapter_path)
    if _sha256_bytes(adapter_path.read_bytes()) != plan["adapter_overlay_sha256"]:
        raise Item32Error("adapter_source_binding")
    fragment = _run(
        ["systemctl", "show", UNIT, "-p", "FragmentPath", "--value"],
        phase="UNIT_FRAGMENT_READBACK",
    ).stdout.decode().strip()
    if not fragment or _sha256_bytes(Path(fragment).read_bytes()) != EXPECTED_UNIT_SHA256:
        raise Item32Error("unit_binding")
    _assert_trends_unit_suspended()
    _assert_fixed_trends_container_absent()
    for label in (
        "item32-readonly-successor",
        "item32-readonly",
        "item32-xhs-diagnostic",
    ):
        if _run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.noteai.task={label}",
            ],
            phase="TASK_CONTAINER_READBACK",
        ).stdout.strip():
            raise Item32Error("item32_container_present")
    inspected = json.loads(_run(["docker", "image", "inspect", IMAGE], phase="IMAGE_INSPECT").stdout)[0]
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
    paths = [
        *IMAGE_SOURCE_CONTAINER_PATHS.values(),
        "/app/model/vendor/spider_xhs/v5/upstream.json" if ACTIVE_V5_PLAN is not None else SIGNER_ASSET_CONTAINER_PATH,
    ]
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
                "--label=com.noteai.task=item32-readonly-successor",
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
            phase="IMAGE_SOURCE_CHECK",
        ).stdout.decode()
    finally:
        _remove_container(source_check_name)
    actual = {
        path: digest
        for digest, path in re.findall(r"^([0-9a-f]{64})\s+(.+)$", actual_output, re.M)
    }
    for source_ref, container_path in IMAGE_SOURCE_CONTAINER_PATHS.items():
        if actual.get(container_path) != plan["image_source_sha256"].get(
            source_ref
        ):
            raise Item32Error("image_source_binding")
    asset_path = "/app/model/vendor/spider_xhs/v5/upstream.json" if ACTIVE_V5_PLAN is not None else SIGNER_ASSET_CONTAINER_PATH
    asset_sha = V5_UPSTREAM_SHA256 if ACTIVE_V5_PLAN is not None else EXPECTED_SIGNER_ASSET_SHA256
    if actual.get(asset_path) != asset_sha:
        raise Item32Error("browser_source_binding")

    browser_check_name = f"noteai-item32-browser-{uuid.uuid4().hex[:12]}"
    browser_check = (
        "import hashlib,json,pathlib,spider_xhs_http as x,hot_keywords;"
        "from security_redaction import sanitize_xhs_response_diagnostics,xhs_response_diagnostics;"
        "expected=" + repr(RUNTIME_OVERLAY_SHA256) + ";"
        "actual={n:hashlib.sha256(pathlib.Path('/app',n).read_bytes()).hexdigest() for n in expected};"
        "assert actual==expected;"
        "p=x.VENDOR_DIR/'xhs_main_260411.js';"
        "u=x.BROWSER_USER_AGENT;"
        "print(json.dumps({'ua_sha256':hashlib.sha256(u.encode()).hexdigest(),"
        "'asset_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),"
        "'exact_match':('userAgent: \\\"'+u+'\\\"') in p.read_text()}))"
    )
    if ACTIVE_V5_PLAN is not None:
        browser_check = (
            "import hashlib,json,pathlib,subprocess,curl_cffi,spider_xhs_http,spider_xhs_v5 as v,hot_keywords,scheduler_a;"
            "expected=" + repr(RUNTIME_OVERLAY_SHA256) + ";"
            "actual={n:hashlib.sha256(pathlib.Path('/app',n).read_bytes()).hexdigest() for n in expected};"
            "assert actual==expected;v.runtime.verify_assets();"
            "assert v.trends_budget('{\"initialization\":2,\"collection\":34,\"total\":36}')=="
            + repr(V5_PHYSICAL_BUDGET) + ";"
            + ("exec(" + repr(V5_NETWORK_CLIENT_PREFLIGHT) + ");" if _is_network_repair_plan(ACTIVE_V5_PLAN) else "") +
            "version=subprocess.check_output(['node','--version'],timeout=10).decode().strip();"
            "print(json.dumps({'protocol':'pc_v5','curl_cffi_version':curl_cffi.__version__,"
            "'node_major':int(version.lstrip('v').split('.')[0]),"
            "'upstream_manifest_sha256':hashlib.sha256((v.runtime.ROOT/'upstream.json').read_bytes()).hexdigest()}))"
        )
    try:
        browser_output = _run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                browser_check_name,
                "--label=com.noteai.task=item32-readonly-successor",
                "--user=999:999",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--network=none",
                "--pids-limit=32",
                "--memory=256m" if ACTIVE_V5_PLAN is not None else "--memory=128m",
                "--cpus=0.25",
                # Real imports initialize only this bounded, disposable SQLite
                # database. No production DB URL or host-writable mount exists.
                "--tmpfs=/tmp/item32-import:rw,nosuid,nodev,noexec,size=8m,mode=0700,uid=999,gid=999",
                "--env=DATABASE_URL=",
                "--env=NOTEAI_SQLITE_PATH=/tmp/item32-import/noteai.db",
                *_runtime_overlay_mounts(adapter_path),
                "--workdir=/app/model",
                "--entrypoint=python",
                IMAGE,
                "-EsB",
                "-c",
                browser_check,
            ],
            timeout=60,
            phase="RUNTIME_OVERLAY_CHECK",
        ).stdout
    finally:
        _remove_container(browser_check_name)
    try:
        browser = json.loads(browser_output)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32Error("browser_runtime_binding") from exc
    expected_browser = {
        "ua_sha256": plan["browser_binding"]["user_agent_sha256"],
        "asset_sha256": EXPECTED_SIGNER_ASSET_SHA256,
        "exact_match": True,
    } if ACTIVE_V5_PLAN is None else {
        "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
        "upstream_manifest_sha256": V5_UPSTREAM_SHA256,
    }
    if browser != expected_browser:
        raise Item32Error("browser_runtime_binding")
    result = {
        "observed_at": _utc_now(),
        "image_config_sha256": EXPECTED_CONFIG_SHA256,
        "registry_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "registry_manifest_provenance": plan["registry_manifest_provenance"],
        "adapter_overlay_sha256": plan["adapter_overlay_sha256"],
        "runtime_overlay_sha256": dict(RUNTIME_OVERLAY_SHA256),
    }
    if ACTIVE_V5_PLAN is None:
        result.update(user_agent_sha256=plan["browser_binding"]["user_agent_sha256"],
                      signer_asset_sha256=EXPECTED_SIGNER_ASSET_SHA256, user_agent_exact_match=True)
    else:
        result.update(browser)
    return result


def _write_env(path: Path, key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise Item32Error("env_value_shape")
    _atomic_write(path, f"{key}={value}\n".encode("utf-8"), 0o600)


def _run_db_probe(
    run_dir: Path,
    db_url: str,
    phase: str,
    container_registry: dict[str, str],
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    probe_path = run_dir / "db_probe.py"
    db_env = run_dir / f"db-{phase}.env"
    _atomic_write(probe_path, DB_PROBE_SOURCE.encode("utf-8"), 0o444)
    _write_env(db_env, "DATABASE_URL", db_url)
    name = f"noteai-item32-db-{phase}-{uuid.uuid4().hex[:12]}"
    container_registry[name] = ""
    try:
        completed = _run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--label=com.noteai.task=item32-readonly-successor",
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
            phase={"before": "DB_BEFORE_PROBE", "after": "DB_AFTER_PROBE"}[phase],
        )
        lines = [line for line in completed.stdout.decode("utf-8").splitlines() if line]
        if len(lines) != 1:
            raise Item32Error("db_probe_output")
        result = json.loads(lines[0])
        if evidence_dir is not None:
            _retain_db_probe(evidence_dir, phase, result)
    finally:
        try:
            db_env.unlink(missing_ok=True)
        finally:
            _remove_registered_container(container_registry, name)
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


def _retain_db_probe(directory: Path, phase: str, result: dict[str, Any]) -> None:
    """Persist the complete safe probe projection before acceptance can fail.

    Connection details, raw stderr and arbitrary fields never enter this record.
    A retained rejected observation is not proof that the database was unchanged.
    """
    booleans = {"server_enforced_read_only", "xid_assigned", "transaction_rolled_back", "secret_values_recorded"}
    integers = {"write_count", "tuple_write_count", "active_or_manual_count", "session_blocked_count", "today_attempt_count"}
    hashes = {"session_identity_sha256", "readback_query_sha256"}
    keys = booleans | integers | hashes | {"observed_at", "write_tables"}
    if (phase not in {"before", "after"} or not isinstance(result, dict) or set(result) != keys
        or any(type(result[name]) is not bool for name in booleans)
        or any(type(result[name]) is not int for name in integers)
        or any(not isinstance(result[name], str) or re.fullmatch(r"[0-9a-f]{64}", result[name]) is None for name in hashes)
        or not isinstance(result["write_tables"], list)
        or any(not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) is None
               for name in result["write_tables"])):
        raise Item32Error("db_probe_output")
    _parse_clock(result["observed_at"])
    path = directory / f"database-{phase}-probe.json"
    if path.exists():
        raise Item32Error("db_probe_already_recorded")
    _atomic_write(path, _json_bytes(result), 0o600)


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
    adapter_path: Path,
    container_registry: dict[str, str],
    signing_storage: str = "",
) -> tuple[str, str, Path]:
    _assert_runtime_overlay_sources(adapter_path)
    task_dir = run_dir / "task-store"
    task_dir.mkdir(mode=0o700)
    os.chown(task_dir, 999, 999)
    cookie_env = runtime_dir / "xhs.env"
    _write_env(cookie_env, "NOTEAI_XHS_COOKIES_JSON", cookie_json)
    if ACTIVE_V5_PLAN is not None:
        if "\n" in signing_storage or "\r" in signing_storage:
            raise Item32Error("env_value_shape")
        _atomic_write(cookie_env, (f"NOTEAI_XHS_COOKIES_JSON={cookie_json}\n"
                                  f"NOTEAI_XHS_WEB_SSK_JSON={signing_storage}\n").encode(), 0o600)
    name = f"noteai-item32-{uuid.uuid4().hex[:16]}"
    container_registry[name] = ""
    command = [
        "docker",
        "create",
        "--pull=never",
        "--name",
        name,
        "--label=com.noteai.task=item32-readonly-successor",
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
        *_runtime_overlay_mounts(adapter_path),
        "--workdir=/app/model",
        *(["--env=NOTEAI_XHS_PROTOCOL=pc_v5",
           '--env=NOTEAI_XHS_V5_BUDGET_JSON={"initialization":2,"collection":34,"total":36}',
           "--env=DATABASE_URL="] if ACTIVE_V5_PLAN is not None else []),
        IMAGE,
        "python",
        "market_timing_worker.py",
        "--once",
    ]
    container_id = ""
    try:
        container_id = _run(command, timeout=60, phase="COLLECTION_CREATE").stdout.decode().strip()
        if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
            raise Item32Error("container_identity")
        container_registry[name] = container_id
        inspection = json.loads(
            _run(["docker", "inspect", container_id], phase="COLLECTION_INSPECT").stdout
        )[0]
        environment = {}
        for item in (inspection.get("Config") or {}).get("Env") or []:
            key, _, value = str(item).partition("=")
            environment[key] = value
        mounts = inspection.get("Mounts") or []
        host = inspection.get("HostConfig") or {}
        if (
            (bool(environment.get("DATABASE_URL")) if ACTIVE_V5_PLAN is not None else "DATABASE_URL" in environment)
            or not environment.get("NOTEAI_XHS_COOKIES_JSON")
            or environment.get("NOTEAI_SQLITE_PATH") != "/task/noteai.db"
            or environment.get("NOTEAI_HOT_KEYWORD_DB_PATH")
            != "/task/hot_keywords.db"
            or len(mounts) != 1 + len(RUNTIME_OVERLAY_SHA256)
            or {
                (mount.get("Destination"), mount.get("Source"), mount.get("RW"))
                for mount in mounts
            }
            != {
                ("/task", str(task_dir), True),
                *((RUNTIME_OVERLAY_CONTAINER_PATHS[name], str(path), False)
                  for name, path in _runtime_overlay_paths(adapter_path).items()),
            }
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
            or (ACTIVE_V5_PLAN is not None and (
                environment.get("NOTEAI_XHS_PROTOCOL") != "pc_v5"
                or environment.get("NOTEAI_XHS_WEB_SSK_JSON") != signing_storage
                or environment.get("NOTEAI_XHS_V5_BUDGET_JSON") != '{"initialization":2,"collection":34,"total":36}'))
        ):
            raise Item32Error("container_boundary")
        cookie_env.unlink(missing_ok=True)
        return name, container_id, cookie_env
    except BaseException:
        try:
            _remove_registered_container(container_registry, name)
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
    real_counts: dict[str, int] = {}
    search_domains: set[str] = set()
    recommend_domains: set[str] = set()
    total = 0
    allowed_sources = REAL_SOURCES | {BASELINE_SOURCE}
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
        real_count = 0
        for row in rows:
            keyword = row.get("keyword") if isinstance(row, dict) else None
            normalized_keyword = (
                keyword.strip() if isinstance(keyword, str) else None
            )
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
                or not normalized_keyword
                or keyword != normalized_keyword
                or normalized_keyword in seen
                or source not in allowed_sources
                or row.get("category") != domain
                or type(row.get("search_vol")) is not int
                or type(row.get("trend_dir")) is not int
                or type(row.get("sample_count")) is not int
                or type(row.get("quality_score")) is not int
                or not 5 <= row["quality_score"] <= 100
                or row.get("evidence_level")
                not in {"weak", "medium", "strong"}
                or not isinstance(row.get("quality_reason"), str)
                or not row["quality_reason"]
                or _parse_clock(row.get("captured_at")) != generated_at
            ):
                raise Item32Error("snapshot_quality")
            seen.add(normalized_keyword)
            qualifies_as_real = (
                source in REAL_SOURCES
                and row["quality_score"] >= 55
                and row["evidence_level"] in {"medium", "strong"}
            )
            if qualifies_as_real:
                real_count += 1
            if qualifies_as_real and source in SEARCH_RESULT_SOURCES:
                search_domains.add(domain)
            if qualifies_as_real and source == "search_recommend":
                recommend_domains.add(domain)
        if real_count < 12:
            raise Item32Error("snapshot_quality")
        real_counts[domain] = real_count
        total += len(rows)
    if search_domains != DOMAINS or recommend_domains != DOMAINS:
        raise Item32Error("snapshot_source_quality")
    if total > 90:
        raise Item32Error("snapshot_limit")
    return real_counts, sorted(search_domains), sorted(recommend_domains), total


def _attempt_count(database: Path) -> tuple[int | None, int | None]:
    if not database.is_file() or database.is_symlink():
        return None, None
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
        return None, None


def _worker_diagnostic_projectors():
    # Pure stdlib-only source, bundled beside tools/ and already part of the
    # runtime overlay binding. Read and compile the same bytes we hash.
    source = Path(__file__).resolve().parents[1] / "model/security_redaction.py"
    raw = source.read_bytes()
    if _sha256_bytes(raw) != RUNTIME_OVERLAY_SHA256["model/security_redaction.py"]:
        raise Item32Error("worker_diagnostic_source_binding")
    namespace = {"__name__": "item32_bound_security_redaction", "__file__": str(source)}
    exec(compile(raw, str(source), "exec"), namespace)
    return namespace["sanitize_trends_http_event"], namespace["sanitize_trends_failure"]


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
    project_http, project_failure = _worker_diagnostic_projectors()
    events: list[dict[str, Any]] = []
    http_events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    invalid_http_events = 0
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
        if not isinstance(value, dict):
            continue
        if value.get("event") == "xhs_trends_http_observation":
            safe = project_http(value)
            if safe and len(http_events) < 72:
                http_events.append(safe)
            else:
                invalid_http_events += 1
            continue
        if value.get("event") == "xhs_trends_provider_failure":
            if len(failures) < 36:
                failures.append(project_failure(value))
            continue
        if value.get("event") not in {
            "trends_run_started",
            "trends_run_succeeded",
            "trends_run_failed",
            "trends_run_skipped",
        }:
            continue
        events.append(
            {key: value[key] for key in sorted(allowed_event_keys) if key in value}
        )
    dispatched = {}
    terminal = {}
    for value in http_events:
        sequence, kind = value["sequence"], value["request_kind"]
        if value["phase"] == "dispatch":
            if sequence in dispatched or sequence != len(dispatched) + 1:
                invalid_http_events += 1
            dispatched[sequence] = kind
        else:
            if (sequence in terminal or dispatched.get(sequence) != kind
                    or (value["phase"] == "response"
                        and "http_status" not in value["response_diagnostics"])):
                invalid_http_events += 1
            terminal[sequence] = value["phase"]
    initialization_count = sum(kind in {"dsl", "session"} for kind in dispatched.values())
    collection_count = len(dispatched) - initialization_count
    initialization_kinds = {
        kind: sum(actual == kind for actual in dispatched.values())
        for kind in ("dsl", "session")
    }
    if initialization_count > 2 or collection_count > 34 or any(count > 1 for count in initialization_kinds.values()):
        invalid_http_events += 1
    receipt = {
        "schema": "noteai.item32.worker_receipt.v1",
        "exit_code": int(exit_code),
        "output_sha256": _sha256_bytes(raw),
        "output_size": len(raw),
        "structured_events": events,
        "physical_http_observations": http_events,
        "provider_failures": failures,
        "physical_http_summary": {
            "initialization_dispatches_observed": initialization_count,
            "initialization_request_counts": initialization_kinds,
            "collection_dispatches_observed": collection_count,
            "response_events_observed": sum(phase == "response" for phase in terminal.values()),
            "unknown_events_observed": sum(phase == "unknown" for phase in terminal.values()),
            "unresolved_dispatches_observed": len(set(dispatched) - set(terminal)),
            "invalid_observations": invalid_http_events,
            "observation_complete": bool(dispatched) and not invalid_http_events and set(dispatched) == set(terminal),
        },
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
    predecessor: dict[str, Any],
    budget: dict[str, Any],
    runtime_readback: dict[str, Any],
) -> Path:
    task_dir = run_dir / "task-store"
    run, attempts, snapshot_raw = _read_task_result(task_dir / "hot_keywords.db")
    execution_clocks = [
        _parse_clock(run["started_at"]),
        _parse_clock(run["completed_at"]),
        *[
            _parse_clock(row[field])
            for row in attempts
            for field in ("admitted_at", "completed_at")
        ],
    ]
    if any(
        value.date().isoformat() != budget["bucket_date"]
        for value in execution_clocks
    ):
        raise Item32Error("execution_bucket")
    start, deadline, finish = _plan_window(plan["admission"])
    if (
        not start <= execution_clocks[0] < deadline
        or any(not start <= value < finish for value in execution_clocks)
    ):
        raise Item32Error("execution_window")
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
    physical = None
    if plan["schema"] == V5_PLAN_SCHEMA:
        physical = _v5_physical_proof(run_dir, plan, run, attempts)
        attempt_payload["physical_http"] = physical
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
        "schema": "noteai.item32.xhs_trends_readonly.v3" if physical is not None else TERMINAL_SCHEMA,
        "item": 32,
        "status": "VERIFIED",
        "readiness_credit": True,
        "observed_at": _utc_now(),
        "successor": {
            "fresh_identity": True,
            "no_replay": True,
            "work_root_identity_sha256": _identity(
                "successor-work-root", str(WORK_ROOT)
            ),
            "predecessor_closure_sha256": predecessor["closure_sha256"],
            "original_admission_sha256": predecessor[
                "original_admission_sha256"
            ],
            "original_store_sha256": predecessor["original_store_sha256"],
            "diagnostic_admission_sha256": predecessor[
                "diagnostic_admission_sha256"
            ],
            "diagnostic_result_sha256": predecessor[
                "diagnostic_result_sha256"
            ],
            "predecessor_provider_call_count": 14 if _is_sep17_plan(plan) or _is_network_repair_plan(plan) else 3 if physical is not None else 2,
            "predecessors_unchanged": True,
            "budget": budget,
            "runtime_readback": runtime_readback,
        },
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
    if physical is not None:
        terminal_payload["successor"]["previous_successor"] = predecessor["previous_successor"]
        if _is_sep17_plan(plan) or _is_network_repair_plan(plan):
            terminal_payload["successor"]["previous_v5_successor"] = predecessor["previous_v5_successor"]
        if _is_network_repair_plan(plan):
            for key in ("previous_v5_initialization_hold", "network_repair_preflight"):
                terminal_payload["successor"][key] = predecessor[key]
        terminal_payload["execution"]["physical_http"] = {
            "initialization_count": 2, "collection_count": 34, "total_count": 36,
            "total_limit": 36, "automatic_retry_count": 0,
            "worker_receipt_sha256": physical["worker_receipt_sha256"],
            "first_homefeed_is_gate": True,
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


def _v5_physical_proof(run_dir: Path, plan: dict[str, Any], run: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    raw = (run_dir / "worker-receipt.json").read_bytes()
    receipt = json.loads(raw)
    expected_kinds = ["dsl", "session", *ENDPOINT_SEQUENCE]
    observations = receipt.get("physical_http_observations")
    if (receipt.get("exit_code") != 0 or receipt.get("provider_failures") != []
        or receipt.get("secret_values_recorded") is not False
        or not isinstance(observations, list) or len(observations) != 72
        or len(attempts) != 34):
        raise Item32Error("physical_http_evidence")
    project_http, _ = _worker_diagnostic_projectors()
    if any(project_http(value) != value for value in observations):
        raise Item32Error("physical_http_evidence")
    start, _, finish = _plan_window(plan["admission"])
    previous_end = _parse_clock(run["started_at"])
    for index, kind in enumerate(expected_kinds):
        dispatch, response = observations[index * 2:index * 2 + 2]
        if (dispatch.get("phase") != "dispatch" or response.get("phase") != "response"
            or any(item.get("request_kind") != kind or item.get("sequence") != index + 1 for item in (dispatch, response))):
            raise Item32Error("physical_http_evidence")
        first, last = _parse_clock(dispatch.get("at")), _parse_clock(response.get("at"))
        if not start <= previous_end <= first <= last <= _parse_clock(run["completed_at"]) < finish:
            raise Item32Error("physical_http_window")
        previous_end = last
        diagnostics = response.get("response_diagnostics", {})
        if (type(diagnostics.get("http_status")) is not int or not 200 <= diagnostics["http_status"] < 300
                or diagnostics.get("message_tags", []) != []):
            raise Item32Error("physical_http_business_failure")
        code = diagnostics.get("business_code")
        code_ok = (type(code) is int and code == 0 and diagnostics.get("business_code_kind") == "integer"
                   or type(code) is str and code == "0" and diagnostics.get("business_code_kind") == "numeric_string")
        recommendation_keys = {"recommendation_items_total", "recommendation_items_usable"}
        recommendation_counts_valid = (
            kind == "search_recommend" and recommendation_keys <= set(diagnostics)
            and type(diagnostics["recommendation_items_total"]) is int
            and type(diagnostics["recommendation_items_usable"]) is int
            and 0 <= diagnostics["recommendation_items_usable"] <= diagnostics["recommendation_items_total"])
        if recommendation_keys & set(diagnostics) and not recommendation_counts_valid:
            raise Item32Error("physical_http_business_failure")
        if recommendation_counts_valid and diagnostics["recommendation_items_usable"] > 0:
            code_ok = code_ok or (
                type(code) is int and code == 1000 and diagnostics.get("business_code_kind") == "integer"
                or type(code) is str and code == "1000" and diagnostics.get("business_code_kind") == "numeric_string")
        if kind != "dsl" and (diagnostics.get("payload_kind") != "object"
                               or diagnostics.get("success_state") != "true"
                               or not code_ok):
            raise Item32Error("physical_http_business_failure")
        if "nested_business_code" in diagnostics and not (
                type(diagnostics["nested_business_code"]) is int and diagnostics["nested_business_code"] == 0
                or type(diagnostics["nested_business_code"]) is str and diagnostics["nested_business_code"] == "0"):
            raise Item32Error("physical_http_business_failure")
        if index >= 2:
            attempt = attempts[index - 2]
            if (attempt["endpoint"] != kind or attempt["status"] != "succeeded"
                or not _parse_clock(attempt["admitted_at"]) <= first <= last <= _parse_clock(attempt["completed_at"])):
                raise Item32Error("physical_http_admission_binding")
    return {"initialization_count": 2, "collection_count": 34, "total_count": 36,
            "total_limit": 36, "automatic_retry_count": 0, "first_homefeed_is_gate": True,
            "worker_receipt_sha256": _sha256_bytes(raw), "observations": observations}


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


def _stage_export(candidate: Path) -> Path:
    """Copy the candidate into the root-owned work root before cleanup."""
    name = (
        ".item32-evidence-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex
        + ".tar.gz.candidate"
    )
    if candidate.parent.parent != WORK_ROOT:
        raise Item32Error("candidate_export_identity")
    work_metadata = os.lstat(WORK_ROOT)
    if (
        not stat.S_ISDIR(work_metadata.st_mode)
        or stat.S_IMODE(work_metadata.st_mode) != 0o700
    ):
        raise Item32Error("work_root_metadata")
    candidate_lstat = os.lstat(candidate)
    if (
        not stat.S_ISREG(candidate_lstat.st_mode)
        or stat.S_IMODE(candidate_lstat.st_mode) != 0o600
        or candidate_lstat.st_uid != work_metadata.st_uid
        or candidate_lstat.st_gid != work_metadata.st_gid
        or candidate_lstat.st_nlink != 1
    ):
        raise Item32Error("candidate_export_metadata")
    source = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW)
    directory = os.open(WORK_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = -1
    staged = False
    try:
        source_metadata = os.fstat(source)
        if (
            source_metadata.st_dev != candidate_lstat.st_dev
            or source_metadata.st_ino != candidate_lstat.st_ino
        ):
            raise Item32Error("candidate_export_identity")
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        source_digest = hashlib.sha256()
        while True:
            chunk = os.read(source, 1024 * 1024)
            if not chunk:
                break
            source_digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short export write")
                view = view[written:]
        os.fsync(descriptor)
        staged_metadata = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        staged_digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            staged_digest.update(chunk)
        candidate_after = os.fstat(source)
        candidate_path_after = os.lstat(candidate)
        if (
            source_digest.digest() != staged_digest.digest()
            or staged_metadata.st_size != source_metadata.st_size
            or candidate_after.st_dev != source_metadata.st_dev
            or candidate_after.st_ino != source_metadata.st_ino
            or candidate_after.st_size != source_metadata.st_size
            or candidate_after.st_mtime_ns != source_metadata.st_mtime_ns
            or candidate_path_after.st_dev != source_metadata.st_dev
            or candidate_path_after.st_ino != source_metadata.st_ino
        ):
            raise Item32Error("candidate_export_changed")
        os.fsync(directory)
        staged = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(source)
        if not staged:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)
    return WORK_ROOT / name


def _publish_export(staged: Path) -> Path:
    pattern = re.compile(
        r"^\.item32-evidence-([0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.gz)\.candidate$"
    )
    match = pattern.fullmatch(staged.name)
    if staged.parent != WORK_ROOT or match is None:
        raise Item32Error("staged_export_identity")
    account = _validated_export_account()
    public_name = f"item32-evidence-{match.group(1)}"
    source_directory = os.open(
        WORK_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    export_directory = os.open(
        EXPORT_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    source = -1
    destination = -1
    destination_created = False
    try:
        work_metadata = os.fstat(source_directory)
        if (
            not stat.S_ISDIR(work_metadata.st_mode)
            or stat.S_IMODE(work_metadata.st_mode) != 0o700
        ):
            raise Item32Error("work_root_metadata")
        source = os.open(
            staged.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=source_directory,
        )
        metadata = os.fstat(source)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != work_metadata.st_uid
            or metadata.st_gid != work_metadata.st_gid
            or metadata.st_nlink != 1
        ):
            raise Item32Error("staged_export_metadata")
        path_metadata = os.stat(
            staged.name,
            dir_fd=source_directory,
            follow_symlinks=False,
        )
        if (
            path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
        ):
            raise Item32Error("staged_export_identity")
        destination = os.open(
            public_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=export_directory,
        )
        destination_created = True
        source_digest = hashlib.sha256()
        while True:
            chunk = os.read(source, 1024 * 1024)
            if not chunk:
                break
            source_digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination, view)
                if written <= 0:
                    raise OSError("short export write")
                view = view[written:]
        os.fsync(destination)
        os.lseek(destination, 0, os.SEEK_SET)
        destination_digest = hashlib.sha256()
        while True:
            chunk = os.read(destination, 1024 * 1024)
            if not chunk:
                break
            destination_digest.update(chunk)
        source_after = os.fstat(source)
        destination_metadata = os.fstat(destination)
        if (
            source_digest.digest() != destination_digest.digest()
            or source_after.st_dev != metadata.st_dev
            or source_after.st_ino != metadata.st_ino
            or source_after.st_size != metadata.st_size
            or source_after.st_mtime_ns != metadata.st_mtime_ns
            or destination_metadata.st_size != metadata.st_size
            or not stat.S_ISREG(destination_metadata.st_mode)
            or destination_metadata.st_nlink != 1
        ):
            raise Item32Error("published_export_changed")
        os.fchmod(destination, 0o600)
        os.fchown(destination, account.pw_uid, account.pw_gid)
        os.fsync(destination)
        destination_metadata = os.fstat(destination)
        destination_path_metadata = os.stat(
            public_name,
            dir_fd=export_directory,
            follow_symlinks=False,
        )
        if (
            stat.S_IMODE(destination_metadata.st_mode) != 0o600
            or destination_metadata.st_uid != account.pw_uid
            or destination_metadata.st_gid != account.pw_gid
            or destination_path_metadata.st_dev != destination_metadata.st_dev
            or destination_path_metadata.st_ino != destination_metadata.st_ino
        ):
            raise Item32Error("published_export_metadata")
        os.unlink(staged.name, dir_fd=source_directory)
        os.fsync(source_directory)
        os.fsync(export_directory)
    except BaseException:
        if destination_created:
            try:
                os.unlink(public_name, dir_fd=export_directory)
                os.fsync(export_directory)
            except Exception:
                pass
        raise
    finally:
        if source >= 0:
            os.close(source)
        if destination >= 0:
            os.close(destination)
        os.close(source_directory)
        os.close(export_directory)
    return EXPORT_ROOT / public_name


def _discard_staged_export(path: Path) -> None:
    if (
        path.parent != WORK_ROOT
        or re.fullmatch(
            r"\.item32-evidence-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.gz\.candidate",
            path.name,
        )
        is None
    ):
        raise Item32Error("staged_export_identity")
    directory = os.open(WORK_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.unlink(path.name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.fsync(directory)
    finally:
        os.close(directory)


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


def execute(
    plan_path: Path,
    executor_path: Path,
    adapter_path: Path,
    hold_evidence_path: Path,
) -> Path:
    if os.geteuid() != 0:
        raise Item32Error("root_required")
    plan, plan_sha256 = _load_plan(
        plan_path, executor_path, adapter_path, hold_evidence_path
    )
    _ensure_work_root()
    lock_descriptor = _acquire_executor_lock()
    try:
        return _execute_locked(
            plan, plan_sha256, executor_path, adapter_path, hold_evidence_path
        )
    finally:
        os.close(lock_descriptor)


def _execute_locked(
    plan: dict[str, Any],
    plan_sha256: str,
    executor_path: Path,
    adapter_path: Path,
    hold_evidence_path: Path,
) -> Path:
    predecessor_locks: list[int] = []
    container_registry: dict[str, str] = {}
    secret_values: dict[str, str] = {}
    run_dir: Path | None = None
    runtime_dir: Path | None = None
    container_name = ""
    container_id = ""
    collection_started = False
    admission_created = False
    post_probe_verified = False
    post_probe_attempted = False
    attempts_readback: int | None = None
    unknown_readback: int | None = None
    candidate: Path | None = None
    staged: Path | None = None
    predecessor: dict[str, Any] = {}
    budget: dict[str, Any] = {}
    runtime_readback: dict[str, Any] = {}
    host_preflight_started = False
    failure: BaseException | None = None
    failure_traceback = None
    try:
        if _admission_path().exists():
            raise Item32Error("item32_already_dispatched")
        if any(EXPORT_ROOT.glob("item32-evidence-*.tar.gz")):
            raise Item32Error("existing_export_requires_reconciliation")
        predecessor_locks = _acquire_predecessor_locks()
        predecessor = _verify_predecessors(plan, hold_evidence_path)
        budget = _admission_budget(plan, predecessor)
        host_preflight_started = True
        runtime_readback = _preflight_host(plan, adapter_path)
        _cleanup_registered_containers({})
        secret_values = _read_secret_env(SECRET_ENV)
        if _prior_attempt_count() != 0:
            raise Item32Error("prior_task_attempts_present")
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=WORK_ROOT))
        os.chmod(run_dir, 0o700)
        runtime_dir = Path(tempfile.mkdtemp(prefix="noteai-item32-", dir=RUNTIME_ROOT))
        os.chmod(runtime_dir, 0o700)
        pre_probe = _run_db_probe(
            runtime_dir,
            secret_values["DATABASE_URL"],
            "before",
            container_registry,
            run_dir,
        )
        if pre_probe["today_attempt_count"] != budget["used_before"]:
            raise Item32Error("utc_budget_not_available")
        container_name, container_id, _cookie_env = _create_collection_container(
            run_dir,
            runtime_dir,
            secret_values["NOTEAI_XHS_COOKIES_JSON"],
            adapter_path,
            container_registry,
            secret_values.get("NOTEAI_XHS_WEB_SSK_JSON", ""),
        )
        container_registry.setdefault(container_name, container_id)
        _assert_dispatch_window(plan, budget, runtime_readback)
        _create_admission(
            _identity("admission", f"{container_id}:{run_dir}"),
            plan_sha256=plan_sha256,
            predecessor=predecessor,
            budget=budget,
            run_directory_name=run_dir.name,
        )
        admission_created = True
        _assert_trends_unit_suspended()
        _assert_fixed_trends_container_absent()
        # The final two host checks may consume the remaining dispatch margin.
        # An admitted but unstarted job stays HOLD if the approved window closes.
        _assert_dispatch_window(plan, budget, runtime_readback)
        collection_started = True
        timed_out = False
        try:
            completed = _run(
                ["docker", "start", "--attach", container_name],
                timeout=900,
                check=False,
                stderr_to_stdout=True,
                phase="COLLECTION_START",
            )
            worker_output = completed.stdout
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            worker_output = bytes(exc.output or b"")
        inspection = json.loads(
            _run(["docker", "inspect", container_name], phase="COLLECTION_INSPECT").stdout
        )[0]
        exit_code = int(((inspection.get("State") or {}).get("ExitCode") or 0))
        _record_worker_receipt(
            run_dir,
            worker_output,
            exit_code=exit_code if not timed_out else 124,
            secret_values=[
                secret_values["DATABASE_URL"],
                secret_values["NOTEAI_XHS_COOKIES_JSON"],
                secret_values.get("NOTEAI_XHS_WEB_SSK_JSON", ""),
                *[
                    str(cookie.get("value") or "")
                    for cookie in json.loads(
                        secret_values["NOTEAI_XHS_COOKIES_JSON"]
                    )
                ],
            ],
        )
        _remove_registered_container(container_registry, container_name)
        container_name = ""
        post_probe_attempted = True
        post_probe = _run_db_probe(
            runtime_dir,
            secret_values["DATABASE_URL"],
            "after",
            container_registry,
            run_dir,
        )
        if post_probe["today_attempt_count"] != pre_probe["today_attempt_count"]:
            raise Item32Error("production_attempt_ledger_changed")
        if post_probe["session_identity_sha256"] != pre_probe["session_identity_sha256"]:
            raise Item32Error("database_identity_changed")
        post_probe_verified = True
        if timed_out:
            raise Item32Error("worker_timeout")
        if exit_code != 0:
            raise Item32Error("worker_failed")
        if _run(
            ["docker", "ps", "-aq", "--filter", "label=com.noteai.task=item32-readonly-successor"],
            phase="TASK_CONTAINER_READBACK",
        ).stdout.strip():
            raise Item32Error("container_cleanup")
        attempts_readback, unknown_readback = _attempt_count(
            run_dir / "task-store" / "hot_keywords.db"
        )
        if attempts_readback != 34 or unknown_readback != 0:
            raise Item32Error("attempt_readback")
        if _verify_predecessors(plan, hold_evidence_path) != predecessor:
            raise Item32Error("predecessor_changed")
        executor_sha256 = _sha256_bytes(executor_path.read_bytes())
        candidate = _build_artifacts(
            run_dir=run_dir,
            plan=plan,
            plan_sha256=plan_sha256,
            executor_sha256=executor_sha256,
            container_id=container_id,
            pre_probe=pre_probe,
            post_probe=post_probe,
            predecessor=predecessor,
            budget=budget,
            runtime_readback=runtime_readback,
        )
        _ensure_export_secret_free(
            candidate,
            [
                secret_values["DATABASE_URL"],
                secret_values["NOTEAI_XHS_COOKIES_JSON"],
                secret_values.get("NOTEAI_XHS_WEB_SSK_JSON", ""),
                *[
                    str(cookie.get("value") or "")
                    for cookie in json.loads(
                        secret_values["NOTEAI_XHS_COOKIES_JSON"]
                    )
                ],
            ],
        )
        staged = _stage_export(candidate)
    except BaseException as exc:
        failure = exc
        failure_traceback = sys.exc_info()[2]

    # Stop every exact registered identity and confirm the closed task label set
    # before reading the isolated attempt ledger. This prevents a running writer
    # or a failed `--rm` from being reported as a stable zero-call outcome.
    cleanup_failed = False
    if host_preflight_started or container_registry:
        try:
            _cleanup_registered_containers(container_registry)
        except Exception:
            cleanup_failed = True
    # A rejected worker receipt or failed exact-container removal must not skip
    # the final read-only observation. Stop known writers first, then probe at
    # most once; an uncertain probe is retained as UNKNOWN, never retried.
    if (collection_started and not post_probe_attempted and not cleanup_failed
            and run_dir is not None and runtime_dir is not None
            and secret_values.get("DATABASE_URL")):
        post_probe_attempted = True
        try:
            post_probe = _run_db_probe(
                runtime_dir, secret_values["DATABASE_URL"], "after", container_registry, run_dir,
            )
            if post_probe["today_attempt_count"] != pre_probe["today_attempt_count"]:
                raise Item32Error("production_attempt_ledger_changed")
            if post_probe["session_identity_sha256"] != pre_probe["session_identity_sha256"]:
                raise Item32Error("database_identity_changed")
            post_probe_verified = True
        except BaseException:
            post_probe_verified = False
        try:
            _cleanup_registered_containers(container_registry)
        except Exception:
            cleanup_failed = True
    if run_dir is not None and run_dir.exists():
        try:
            _atomic_write(run_dir / "database-proof-state.json", _json_bytes({
                "schema": "noteai.item32.retained_db_probe_state.v1",
                "before_recorded": (run_dir / "database-before-probe.json").is_file(),
                "after_recorded": (run_dir / "database-after-probe.json").is_file(),
                "after_attempted": post_probe_attempted,
                "after_verified": post_probe_verified,
                "collection_started": collection_started,
                "automatic_retry_count": 0,
                "readiness_credit": False,
            }), 0o600)
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
    for descriptor in predecessor_locks:
        try:
            os.close(descriptor)
        except OSError:
            cleanup_failed = True

    if admission_created:
        if collection_started:
            if cleanup_failed or run_dir is None:
                attempts_readback, unknown_readback = None, None
            else:
                attempts_readback, unknown_readback = _attempt_count(
                    run_dir / "task-store" / "hot_keywords.db"
                )
        else:
            attempts_readback, unknown_readback = 0, 0

    terminal_ready = (
        failure is None
        and not cleanup_failed
        and staged is not None
        and attempts_readback == 34
        and unknown_readback == 0
    )
    # The isolated store, receipt and candidate are recovery records, not
    # transient Secret files. Keep them even after a successful export.
    if not terminal_ready and failure is None and not cleanup_failed:
        failure = Item32Error("terminal_staging")
        failure_traceback = failure.__traceback__
    elif (failure is not None and not collection_started and run_dir is not None
          and not (run_dir / "database-before-probe.json").exists()):
        try:
            shutil.rmtree(run_dir)
        except FileNotFoundError:
            pass
        except Exception:
            cleanup_failed = True
        if run_dir.exists():
            cleanup_failed = True

    if failure is not None or cleanup_failed:
        generated_cleanup_failed = False
        if staged is not None:
            try:
                _discard_staged_export(staged)
                staged = None
            except Exception:
                generated_cleanup_failed = True
        if run_dir is not None and run_dir.exists():
            try:
                _discard_generated_artifacts(run_dir)
            except Exception:
                generated_cleanup_failed = True
        if generated_cleanup_failed:
            print(
                "ITEM32_CLEANUP_HOLD generated_artifact_residue=UNKNOWN",
                file=sys.stderr,
                flush=True,
            )
        if admission_created:
            try:
                _update_admission(
                    "HOLD", attempts_readback, unknown_readback
                )
            except Exception:
                pass
        if collection_started:
            database_status = "0" if post_probe_verified else "UNKNOWN"
            calls_text = (
                "UNKNOWN" if attempts_readback is None else str(attempts_readback)
            )
            unknown_text = (
                "UNKNOWN" if unknown_readback is None else str(unknown_readback)
            )
            physical_text = ""
            if ACTIVE_V5_PLAN is not None:
                physical_count: int | str = "UNKNOWN"
                complete = False
                try:
                    receipt = json.loads((run_dir / "worker-receipt.json").read_bytes())
                    summary = receipt["physical_http_summary"]
                    initial = summary["initialization_dispatches_observed"]
                    collected = summary["collection_dispatches_observed"]
                    if type(initial) is int and type(collected) is int and 0 <= initial <= 2 and 0 <= collected <= 34:
                        physical_count = initial + collected
                        complete = summary.get("observation_complete") is True
                except (OSError, ValueError, TypeError, KeyError):
                    pass
                physical_text = f" physical_http_dispatches_observed={physical_count} physical_observation_complete={str(complete).lower()}"
            print(
                "ITEM32_EXECUTION_HOLD"
                + (f" collection_calls={calls_text}" if ACTIVE_V5_PLAN is not None else f" provider_calls={calls_text}")
                + physical_text
                +
                f" outcome_unknown_count={unknown_text}"
                f" retained_store_identity_sha256={_identity('retained-store', str(run_dir))}"
                " automatic_retry_count=0"
                f" production_db_writes={database_status}",
                flush=True,
            )
        if cleanup_failed:
            print(
                "ITEM32_CLEANUP_HOLD container_or_runtime_residue=UNKNOWN",
                file=sys.stderr,
                flush=True,
            )
        if failure is not None:
            raise failure.with_traceback(failure_traceback)
        raise Item32Error("cleanup_incomplete")

    if staged is None or attempts_readback != 34 or unknown_readback != 0:
        if admission_created:
            try:
                _update_admission(
                    "HOLD", attempts_readback, unknown_readback
                )
            except Exception:
                pass
        raise Item32Error("terminal_staging")
    try:
        published = _publish_export(staged)
        _update_admission("SUCCEEDED", attempts_readback, unknown_readback)
        return published
    except BaseException:
        # Publication or admission sealing may fail after collection succeeded.
        # Retain the hidden candidate and isolated store for read-only recovery.
        try:
            _update_admission("HOLD", attempts_readback, unknown_readback)
        except Exception:
            pass
        raise


def read_retained_result() -> dict[str, Any]:
    """Read existing recovery bytes only; never reconcile by dispatching work.

    A retained file digest proves availability, not a supplier outcome. The
    current worker/runtime state and terminal Evidence still need separate
    authorized readback. Old admissions without a bound run remain UNKNOWN.
    """
    result: dict[str, Any] = {
        "status": "UNKNOWN_HOLD",
        "readiness_credit": False,
        "no_replay": True,
        "runtime_state": "NOT_READ",
    }
    descriptors: list[int] = []

    def directory(name: str | Path, parent: int | None = None, *, store: bool = False) -> int:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        descriptors.append(fd)
        meta = os.fstat(fd)
        owners = {os.geteuid(), 999} if store else {os.geteuid()}
        if meta.st_uid not in owners or stat.S_IMODE(meta.st_mode) != 0o700:
            raise Item32Error("recovery_directory_metadata")
        return fd

    def read_file(parent: int, name: str, limit: int, *, store: bool = False) -> bytes:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid not in ({os.geteuid(), 999} if store else {os.geteuid()})
                or (stat.S_IMODE(before.st_mode) & 0o022 if store else stat.S_IMODE(before.st_mode) != 0o600)
                or not 0 < before.st_size <= limit
            ):
                raise Item32Error("recovery_file_metadata")
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(fd)
            linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                len(raw) != before.st_size
                or (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                != (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                or (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise Item32Error("recovery_file_changed")
            return raw
        finally:
            os.close(fd)

    try:
        root = directory(WORK_ROOT)
        # Open only: a readback must not create a lock or an admission.
        lock = os.open("executor.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        descriptors.append(lock)
        meta = os.fstat(lock)
        if (
            not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1
            or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o600
        ):
            raise Item32Error("recovery_lock_metadata")
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        linked_lock = os.stat("executor.lock", dir_fd=root, follow_symlinks=False)
        if (linked_lock.st_dev, linked_lock.st_ino) != (meta.st_dev, meta.st_ino):
            raise Item32Error("recovery_lock_changed")
        raw = read_file(root, "item32-admission.json", 65536)
        admission = json.loads(raw)
        name = admission.get("run_directory_name")
        if (
            admission.get("schema") != "noteai.item32.successor_admission.v1"
            or admission.get("status") not in {"DISPATCHED", "HOLD", "SUCCEEDED"}
            or admission.get("no_replay") is not True
            or type(admission.get("automatic_retry_count")) is not int
            or admission["automatic_retry_count"] != 0
            or admission.get("predecessor_closure_sha256") != HOLD_EVIDENCE_SHA256
            or not isinstance(name, str)
            or re.fullmatch(r"run-[a-zA-Z0-9_-]{1,64}", name) is None
        ):
            raise Item32Error("recovery_admission_binding")
        result.update(admission_sha256=_sha256_bytes(raw), admission_status=admission["status"])
        run = directory(name, root)
        task_store = directory("task-store", run, store=True)
        files = {}
        for label, parent, filename, limit in (
            ("store", task_store, "hot_keywords.db", 64 * 1024 * 1024),
            ("worker_receipt", run, "worker-receipt.json", 4 * 1024 * 1024),
            ("candidate", run, "item32-evidence.candidate.tar.gz", 8 * 1024 * 1024),
        ):
            try:
                raw = read_file(parent, filename, limit, store=label == "store")
                files[label] = {"sha256": _sha256_bytes(raw), "size": len(raw)}
            except FileNotFoundError:
                files[label] = {"status": "MISSING_UNKNOWN"}
        result["retained_files"] = files
        probes = {}
        for phase in ("before", "after"):
            try:
                raw = read_file(run, f"database-{phase}-probe.json", 65536)
                probes[phase] = {"sha256": _sha256_bytes(raw), "size": len(raw)}
            except FileNotFoundError:
                probes[phase] = {"status": "MISSING_UNKNOWN"}
        result["database_probe_files"] = probes
        if all("sha256" in value for value in files.values()):
            result["status"] = "RETAINED_BYTES_READBACK_ONLY"
        linked_lock = os.stat("executor.lock", dir_fd=root, follow_symlinks=False)
        if (linked_lock.st_dev, linked_lock.st_ino) != (meta.st_dev, meta.st_ino):
            raise Item32Error("recovery_lock_changed")
    except (OSError, ValueError, TypeError, AttributeError, Item32Error):
        # No raw path, exception, receipt event or database content is emitted.
        result["status"] = "UNKNOWN_HOLD"
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return result


def main(argv: list[str] | None = None) -> int:
    global WORK_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--readback-only", action="store_true")
    parser.add_argument("--v5-readback-only", action="store_true")
    parser.add_argument("--v5-sep17-readback-only", action="store_true")
    parser.add_argument("--v5-network-repair-readback-only", action="store_true")
    parser.add_argument("--plan")
    parser.add_argument("--adapter")
    parser.add_argument("--hold-evidence")
    args = parser.parse_args(argv)
    if args.readback_only or args.v5_readback_only or args.v5_sep17_readback_only or args.v5_network_repair_readback_only:
        if args.plan or args.adapter or args.hold_evidence:
            parser.error("readback-only does not accept execution inputs")
        if sum((args.readback_only, args.v5_readback_only, args.v5_sep17_readback_only, args.v5_network_repair_readback_only)) != 1:
            parser.error("select one retained identity")
        if args.v5_readback_only:
            WORK_ROOT = V5_WORK_ROOT
        if args.v5_sep17_readback_only:
            WORK_ROOT = V5_SEP17_WORK_ROOT
        if args.v5_network_repair_readback_only:
            WORK_ROOT = V5_NETWORK_WORK_ROOT
        result = read_retained_result()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "RETAINED_BYTES_READBACK_ONLY" else 2
    if not all((args.plan, args.adapter, args.hold_evidence)):
        parser.error("execution requires plan, adapter and hold-evidence")
    executor_path = Path(__file__).resolve()
    try:
        export_path = execute(
            Path(args.plan).resolve(),
            executor_path,
            Path(args.adapter).resolve(),
            Path(args.hold_evidence).resolve(),
        )
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
        + (" physical_http_count=36 initialization_count=2" if ACTIVE_V5_PLAN is not None else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
