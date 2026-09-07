#!/usr/bin/env python3
"""Run one sanitized XHS homefeed diagnostic after the sealed Item32 HOLD.

This is preparation-only and can never grant Item32 readiness credit.  The
host mode verifies the retained HOLD, creates a fresh no-replay admission,
and starts one isolated container.  The container mode makes exactly one
homefeed request and emits response shape and stable classifications only.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "noteai.item32.xhs_diagnostic_result.v1"
PLAN_SCHEMA = "noteai.item32.xhs_diagnostic_plan.v1"
ADMISSION_SCHEMA = "noteai.item32.xhs_diagnostic_admission.v1"
IMAGE_CONFIG_SHA256 = (
    "a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
)
IMAGE = f"sha256:{IMAGE_CONFIG_SHA256}"
IMAGE_MANIFEST_SHA256 = (
    "406445820107cda130698b157a20663b99697a0acdae65030784d3cb083c1e50"
)
SEALED_EXECUTOR_SHA256 = (
    "ed0cb9e59a4bc4d40760fbd83410ac8852a950b8737340e501d736aab817f662"
)
SEALED_PLAN_SHA256 = (
    "45e32a843a26816a0af4227c335f5cf72525e8fec326031200069f397082fe52"
)
SIGNER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 "
    "Safari/537.36 Edg/138.0.0.0"
)
UNIT = "noteai-xhs-trends.service"
SECRET_ENV = Path("/etc/noteai/xhs-trends.env")
SEALED_ADMISSION = Path(
    "/var/lib/noteai/item32-readonly/item32-admission.json"
)
SEALED_WORK_ROOT = Path("/var/lib/noteai/item32-readonly")
EXPORT_ROOT = Path("/home/ecs-assist-user")
FIXED_TRENDS_CONTAINER = "noteai-xhs-trends"
WORK_ROOT = Path("/var/lib/noteai/item32-xhs-diagnostic")
ADMISSION = WORK_ROOT / "admission.json"
RESULT = WORK_ROOT / "result.json"
RESULT_CANDIDATE = WORK_ROOT / ".result.candidate.json"
ISOLATED_SQLITE_PATH = Path("/tmp/item32-diagnostic.db")
EXPECTED_SECRET_KEYS = {"DATABASE_URL", "NOTEAI_XHS_COOKIES_JSON"}
EXPECTED_COOKIE_NAMES = {"a1", "web_session"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_TIMEOUT_SECONDS = 20.0

_LOGIN_MARKERS = (
    "login required",
    "sign-in required",
    "sign in required",
    "not logged in",
    "session expired",
    "logged out",
    "please log in",
    "please login",
    "请先登录",
    "需要登录",
    "未登陆",
    "未登录",
    "登录已过期",
    "登录过期",
    "会话过期",
    "会话失效",
    "退出登录",
    "重新登录",
)
_INTERACTIVE_MARKERS = (
    "captcha",
    "challenge",
    "sms",
    "验证码",
    "短信",
    "滑块",
    "扫码",
    "重新扫码",
    "扫码登录",
    "请完成验证",
    "人机验证",
    "安全验证",
)
_RISK_MARKERS = (
    "risk control",
    "abnormal login",
    "风控",
    "异常登录",
    "账号异常",
    "安全风险",
)
_ACCOUNT_MARKERS = (
    "account restricted",
    "account disabled",
    "access denied",
    "access restricted",
    "forbidden",
    "permission denied",
    "no permission",
    "账号限制",
    "账号封禁",
    "账户限制",
    "禁止访问",
    "拒绝访问",
    "访问受限",
    "无权限",
)
_COOLDOWN_MARKERS = (
    "too many",
    "cooldown",
    "rate limit",
    "频繁",
    "访问过快",
)

RESULT_KEYS = {
    "classification",
    "owner_gate_required",
    "owner_gate_kind",
    "response_received",
    "http_status",
    "payload_shape",
    "success_state",
    "code_state",
    "marker_class",
    "data_shape",
    "items_shape",
    "item_count",
    "provider_call_count",
    "outcome_unknown_count",
    "automatic_retry_count",
    "isolated_sqlite_state",
}
CLASSIFICATIONS = {
    "SUCCESS_SHAPE",
    "LOGIN_REQUIRED",
    "ACCESS_REVIEW_REQUIRED",
    "INTERACTIVE_VERIFICATION_REQUIRED",
    "RISK_CONTROL_REVIEW_REQUIRED",
    "ACCOUNT_ACCESS_REVIEW_REQUIRED",
    "COOLDOWN_HOLD",
    "REQUEST_CONTRACT_REJECTION",
    "PROVIDER_SERVER_REJECTION",
    "REMOTE_HTTP_REJECTION",
    "ENGINEERING_KNOWN_REJECTION",
    "ENGINEERING_RESPONSE_SCHEMA",
    "ENGINEERING_LOCAL_REJECTION",
    "UNKNOWN_HOLD",
}
MARKER_CLASSES = {
    "NONE",
    "LOGIN",
    "INTERACTIVE_VERIFICATION",
    "RISK_CONTROL",
    "ACCOUNT_ACCESS",
    "COOLDOWN",
}
CLEANUP_STATES = {"ABSENT", "PRESENT", "UNKNOWN"}


class Item32DiagnosticError(RuntimeError):
    """Stable failure code that never includes callback or provider data."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_regular_file(path: Path, *, max_size: int) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= max_size
        ):
            raise Item32DiagnosticError("sealed_store_metadata")
        digest = hashlib.sha256()
        remaining = max_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining <= 0 and os.read(descriptor, 1):
            raise Item32DiagnosticError("sealed_store_metadata")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, value: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def _read_regular_root_file(path: Path, *, max_size: int) -> bytes:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= max_size
    ):
        raise Item32DiagnosticError("protected_file_metadata")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = b""
        while True:
            chunk = os.read(descriptor, 8192)
            if not chunk:
                break
            raw += chunk
            if len(raw) > max_size:
                raise Item32DiagnosticError("protected_file_size")
        return raw
    finally:
        os.close(descriptor)


def _assert_staged_source(path: Path) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= 1024 * 1024
    ):
        raise Item32DiagnosticError("staged_source_metadata")


def _read_secret_values(path: Path = SECRET_ENV) -> dict[str, str]:
    raw = _read_regular_root_file(path, max_size=65536)
    try:
        rows = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Item32DiagnosticError("secret_encoding") from exc
    parsed: dict[str, str] = {}
    for row in rows:
        stripped = row.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if (
            not separator
            or key in parsed
            or key not in EXPECTED_SECRET_KEYS
            or not value
        ):
            raise Item32DiagnosticError("secret_shape")
        parsed[key] = value
    if set(parsed) != EXPECTED_SECRET_KEYS:
        raise Item32DiagnosticError("secret_shape")
    try:
        cookies = json.loads(parsed["NOTEAI_XHS_COOKIES_JSON"])
    except (TypeError, ValueError) as exc:
        raise Item32DiagnosticError("cookie_shape") from exc
    if not isinstance(cookies, list) or len(cookies) != 2:
        raise Item32DiagnosticError("cookie_shape")
    names: set[str] = set()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise Item32DiagnosticError("cookie_shape")
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
            raise Item32DiagnosticError("cookie_shape")
        names.add(name)
    if names != EXPECTED_COOKIE_NAMES:
        raise Item32DiagnosticError("cookie_shape")
    return parsed


def _load_plan(
    path: Path,
    executor_path: Path,
    adapter_path: Path,
) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32DiagnosticError("plan_shape") from exc
    sealed_admission_sha256 = plan.get("sealed_admission_sha256")
    sealed_store_sha256 = plan.get("sealed_store_sha256")
    if (
        not isinstance(sealed_admission_sha256, str)
        or SHA256.fullmatch(sealed_admission_sha256) is None
        or not isinstance(sealed_store_sha256, str)
        or SHA256.fullmatch(sealed_store_sha256) is None
    ):
        raise Item32DiagnosticError("plan_binding")
    expected = {
        "schema": PLAN_SCHEMA,
        "item": 32,
        "status": "PREPARED_NOT_EXECUTED",
        "readiness_credit": False,
        "diagnostic_only": True,
        "outer_executor": "tools/execute_item32_xhs_diagnostic.py",
        "outer_executor_sha256": _sha256_bytes(executor_path.read_bytes()),
        "adapter_source": "model/spider_xhs_http.py",
        "adapter_source_sha256": _sha256_bytes(adapter_path.read_bytes()),
        "existing_image_config_sha256": IMAGE_CONFIG_SHA256,
        "existing_registry_manifest_sha256": IMAGE_MANIFEST_SHA256,
        "existing_registry_manifest_provenance": (
            "HISTORICAL_SEALED_PLAN_ONLY"
        ),
        "sealed_executor_sha256": SEALED_EXECUTOR_SHA256,
        "sealed_plan_sha256": SEALED_PLAN_SHA256,
        "sealed_admission_sha256": sealed_admission_sha256,
        "sealed_store_sha256": sealed_store_sha256,
        "sealed_admission_required_status": "HOLD",
        "request": {
            "method": "POST",
            "endpoint": "/api/sns/web/v1/homefeed",
            "category": "homefeed_recommend",
            "max_pages": 1,
            "max_items": 20,
            "user_agent": SIGNER_USER_AGENT,
            "timeout_seconds": 20,
            "follow_redirects": False,
        },
        "bounds": {
            "provider_requests": 1,
            "prior_sealed_provider_requests": 1,
            "cumulative_provider_requests": 2,
            "automatic_retry": 0,
            "production_database_queries": 0,
            "production_database_writes": 0,
            "cloud_resource_mutations": 0,
            "readiness_credit": False,
        },
    }
    if plan != expected:
        raise Item32DiagnosticError("plan_binding")
    return plan, _sha256_bytes(raw)


def _marker_text(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    values = [payload.get(key) for key in ("msg", "message", "code")]
    data = payload.get("data")
    if isinstance(data, Mapping):
        values.extend(data.get(key) for key in ("msg", "message", "code"))
    return " ".join(
        str(value).casefold() for value in values if value is not None
    )[:500]


def _marker_class(payload: Any) -> str:
    text = _marker_text(payload)
    if any(marker in text for marker in _ACCOUNT_MARKERS):
        return "ACCOUNT_ACCESS"
    if any(marker in text for marker in _RISK_MARKERS):
        return "RISK_CONTROL"
    if any(marker in text for marker in _INTERACTIVE_MARKERS):
        return "INTERACTIVE_VERIFICATION"
    if any(marker in text for marker in _LOGIN_MARKERS):
        return "LOGIN"
    if any(marker in text for marker in _COOLDOWN_MARKERS):
        return "COOLDOWN"
    return "NONE"


def _redirect_marker(location: Any) -> str:
    if not isinstance(location, str):
        return "NONE"
    value = location.casefold()[:500]
    if any(token in value for token in ("captcha", "challenge", "verify")):
        return "INTERACTIVE_VERIFICATION"
    if any(token in value for token in ("risk", "abnormal")):
        return "RISK_CONTROL"
    if any(token in value for token in ("login", "signin", "passport")):
        return "LOGIN"
    return "NONE"


def _owner_gate(classification: str) -> tuple[bool, str]:
    gates = {
        "LOGIN_REQUIRED": "XHS_LOGIN",
        "ACCESS_REVIEW_REQUIRED": "XHS_ACCESS_REVIEW",
        "INTERACTIVE_VERIFICATION_REQUIRED": "XHS_INTERACTIVE_VERIFICATION",
        "RISK_CONTROL_REVIEW_REQUIRED": "XHS_RISK_CONTROL_REVIEW",
        "ACCOUNT_ACCESS_REVIEW_REQUIRED": "XHS_ACCOUNT_ACCESS_REVIEW",
    }
    kind = gates.get(classification, "NONE")
    return kind != "NONE", kind


def classify_response(
    status_code: int,
    payload: Any,
    *,
    redirect_marker: str = "NONE",
) -> dict[str, Any]:
    """Return response shape only; raw provider values are never returned."""

    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise Item32DiagnosticError("response_status")
    is_object = isinstance(payload, Mapping)
    success = payload.get("success") if is_object else None
    if not is_object or "success" not in payload:
        success_state = "ABSENT"
    elif success is True:
        success_state = "TRUE"
    elif success is False:
        success_state = "FALSE"
    else:
        success_state = "OTHER"
    if not is_object or "code" not in payload:
        code_state = "ABSENT"
    elif payload.get("code") in (None, 0, "0", "", "ok", "success"):
        code_state = "ACCEPTED"
    else:
        code_state = "REJECTED"
    data = payload.get("data") if is_object else None
    data_shape = "OBJECT" if isinstance(data, Mapping) else (
        "ABSENT" if data is None else "OTHER"
    )
    items = data.get("items") if isinstance(data, Mapping) else None
    items_shape = "LIST" if isinstance(items, list) else (
        "ABSENT" if items is None else "OTHER"
    )
    item_count = min(len(items), 21) if isinstance(items, list) else 0

    marker = _marker_class(payload)
    if redirect_marker not in MARKER_CLASSES:
        raise Item32DiagnosticError("redirect_marker")
    if 300 <= status_code <= 399 and redirect_marker != "NONE":
        marker = redirect_marker

    if marker == "ACCOUNT_ACCESS":
        classification = "ACCOUNT_ACCESS_REVIEW_REQUIRED"
    elif marker == "RISK_CONTROL":
        classification = "RISK_CONTROL_REVIEW_REQUIRED"
    elif marker == "INTERACTIVE_VERIFICATION":
        classification = "INTERACTIVE_VERIFICATION_REQUIRED"
    elif marker == "LOGIN" or status_code == 401:
        classification = "LOGIN_REQUIRED"
    elif marker == "COOLDOWN" or status_code == 429:
        classification = "COOLDOWN_HOLD"
    elif status_code == 403:
        classification = "ACCESS_REVIEW_REQUIRED"
    elif status_code in {400, 404, 405, 415, 422}:
        classification = "REQUEST_CONTRACT_REJECTION"
    elif 500 <= status_code <= 599:
        classification = "PROVIDER_SERVER_REJECTION"
    elif not 200 <= status_code <= 299:
        classification = "REMOTE_HTTP_REJECTION"
    elif not is_object:
        classification = "ENGINEERING_RESPONSE_SCHEMA"
    elif success_state == "OTHER":
        classification = "ENGINEERING_RESPONSE_SCHEMA"
    elif success_state == "FALSE" or code_state == "REJECTED":
        classification = "ENGINEERING_KNOWN_REJECTION"
    elif (
        data_shape != "OBJECT"
        or items_shape != "LIST"
        or item_count > 20
    ):
        classification = "ENGINEERING_RESPONSE_SCHEMA"
    else:
        classification = "SUCCESS_SHAPE"
    gate_required, gate_kind = _owner_gate(classification)
    return {
        "classification": classification,
        "owner_gate_required": gate_required,
        "owner_gate_kind": gate_kind,
        "response_received": True,
        "http_status": status_code,
        "payload_shape": "OBJECT" if is_object else "OTHER",
        "success_state": success_state,
        "code_state": code_state,
        "marker_class": marker,
        "data_shape": data_shape,
        "items_shape": items_shape,
        "item_count": item_count,
        "provider_call_count": 1,
        "outcome_unknown_count": 0,
        "automatic_retry_count": 0,
        "isolated_sqlite_state": "INITIALIZED",
    }


def classify_no_response(
    *,
    request_started: bool,
    adapter_code: str,
    isolated_sqlite_state: str | None = None,
) -> dict[str, Any]:
    if isolated_sqlite_state is None:
        isolated_sqlite_state = (
            "UNKNOWN" if request_started else "NOT_INITIALIZED"
        )
    if isolated_sqlite_state not in {
        "INITIALIZED",
        "NOT_INITIALIZED",
        "UNKNOWN",
    }:
        raise Item32DiagnosticError("isolated_sqlite_state")
    code = str(adapter_code or "")
    if request_started:
        classification = "UNKNOWN_HOLD"
        calls = 1
        unknown = 1
    elif code in {"login_required", "server_session_logged_out"}:
        classification = "LOGIN_REQUIRED"
        calls = 0
        unknown = 0
    elif code in {"challenge", "login_or_challenge_required"}:
        classification = "INTERACTIVE_VERIFICATION_REQUIRED"
        calls = 0
        unknown = 0
    elif code == "cooldown":
        classification = "COOLDOWN_HOLD"
        calls = 0
        unknown = 0
    else:
        classification = "ENGINEERING_LOCAL_REJECTION"
        calls = 0
        unknown = 0
    gate_required, gate_kind = _owner_gate(classification)
    return {
        "classification": classification,
        "owner_gate_required": gate_required,
        "owner_gate_kind": gate_kind,
        "response_received": False,
        "http_status": None,
        "payload_shape": "ABSENT",
        "success_state": "ABSENT",
        "code_state": "ABSENT",
        "marker_class": "NONE",
        "data_shape": "ABSENT",
        "items_shape": "ABSENT",
        "item_count": 0,
        "provider_call_count": calls,
        "outcome_unknown_count": unknown,
        "automatic_retry_count": 0,
        "isolated_sqlite_state": isolated_sqlite_state,
    }


def _container_runner() -> int:
    import logging

    import httpx

    model_dir = Path("/app/model")
    if str(model_dir) not in sys.path:
        sys.path.insert(0, str(model_dir))
    if (
        os.environ.get("NOTEAI_SQLITE_PATH")
        != str(ISOLATED_SQLITE_PATH)
        or os.environ.get("DATABASE_URL")
        or os.environ.get("NOTEAI_XHS_SERVICE")
    ):
        print(
            json.dumps(
                classify_no_response(
                    request_started=False,
                    adapter_code="isolated_database_boundary",
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    try:
        import db

        db.init_db()
        if not ISOLATED_SQLITE_PATH.is_file():
            raise RuntimeError("isolated_database_missing")
    except Exception:
        print(
            json.dumps(
                classify_no_response(
                    request_started=False,
                    adapter_code="isolated_database_initialization",
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    import spider_xhs_http

    logging.disable(logging.CRITICAL)
    signer_source = (
        spider_xhs_http.VENDOR_DIR / "xhs_main_260411.js"
    ).read_text(encoding="utf-8")
    if 'userAgent: "' + SIGNER_USER_AGENT + '"' not in signer_source:
        result = classify_no_response(
            request_started=False,
            adapter_code="user_agent_binding",
            isolated_sqlite_state="INITIALIZED",
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0

    captured: dict[str, Any] = {
        "requests": 0,
        "status": None,
        "payload": None,
        "redirect_marker": "NONE",
    }

    def capture_request(request: Any) -> None:
        captured["requests"] += 1
        if captured["requests"] > 1:
            raise RuntimeError("request_bound")
        request.headers["user-agent"] = SIGNER_USER_AGENT

    def capture_response(response: Any) -> None:
        response.read()
        captured["status"] = int(response.status_code)
        captured["redirect_marker"] = _redirect_marker(
            (getattr(response, "headers", {}) or {}).get("location", "")
        )
        try:
            captured["payload"] = response.json()
        except Exception:
            captured["payload"] = None

    client = httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        event_hooks={
            "request": [capture_request],
            "response": [capture_response],
        },
    )
    try:
        adapter = spider_xhs_http.SpiderXHSHTTPAdapter(client=client)
        health = adapter.session_health()
        if health.get("status") != "ready":
                result = classify_no_response(
                    request_started=False,
                    adapter_code="login_required",
                    isolated_sqlite_state="INITIALIZED",
            )
        else:
            adapter_code = ""
            try:
                adapter.homefeed(
                    category="homefeed_recommend",
                    max_pages=1,
                    max_items=20,
                )
            except Exception as exc:
                adapter_code = str(getattr(exc, "code", "") or "")
            if captured["status"] is not None:
                result = classify_response(
                    captured["status"],
                    captured["payload"],
                    redirect_marker=captured["redirect_marker"],
                )
            else:
                result = classify_no_response(
                    request_started=captured["requests"] >= 1,
                    adapter_code=adapter_code,
                    isolated_sqlite_state="INITIALIZED",
                )
    finally:
        client.close()
    if result["provider_call_count"] != captured["requests"]:
        result = classify_no_response(
            request_started=captured["requests"] >= 1,
            adapter_code="request_accounting",
            isolated_sqlite_state="INITIALIZED",
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _run(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    stderr_to_null: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if stderr_to_null else subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise Item32DiagnosticError("command_failed")
    return completed


def _ensure_work_root() -> None:
    WORK_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = os.lstat(WORK_ROOT)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != 0
        or metadata.st_gid != 0
    ):
        raise Item32DiagnosticError("work_root_metadata")


def _acquire_lock() -> int:
    descriptor = os.open(
        WORK_ROOT / "executor.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
        ):
            raise Item32DiagnosticError("executor_lock_metadata")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _acquire_sealed_executor_lock() -> int:
    path = SEALED_WORK_ROOT / "executor.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
        ):
            raise Item32DiagnosticError("sealed_executor_lock_metadata")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _parse_clock(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise Item32DiagnosticError("sealed_hold_clock")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Item32DiagnosticError("sealed_hold_clock") from exc
    if parsed.tzinfo is None:
        raise Item32DiagnosticError("sealed_hold_clock")
    return parsed.astimezone(timezone.utc)


def _verify_sealed_hold(plan: Mapping[str, Any]) -> dict[str, str]:
    raw = _read_regular_root_file(SEALED_ADMISSION, max_size=16384)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Item32DiagnosticError("sealed_hold_shape") from exc
    expected_admission_keys = {
        "schema",
        "status",
        "created_at",
        "run_identity_sha256",
        "automatic_retry_count",
        "updated_at",
        "provider_calls",
        "outcome_unknown_count",
    }
    if (
        set(payload) != expected_admission_keys
        or payload.get("schema") != "noteai.item32.execution_admission.v1"
        or payload.get("status") != "HOLD"
        or SHA256.fullmatch(str(payload.get("run_identity_sha256") or ""))
        is None
        or payload.get("provider_calls") != 1
        or payload.get("outcome_unknown_count") != 0
        or payload.get("automatic_retry_count") != 0
    ):
        raise Item32DiagnosticError("sealed_hold_binding")
    if _parse_clock(payload["updated_at"]) < _parse_clock(payload["created_at"]):
        raise Item32DiagnosticError("sealed_hold_binding")
    admission_sha256 = _sha256_bytes(raw)
    if admission_sha256 != plan.get("sealed_admission_sha256"):
        raise Item32DiagnosticError("sealed_admission_digest")

    run_directories = sorted(SEALED_WORK_ROOT.glob("run-*"))
    if len(run_directories) != 1:
        raise Item32DiagnosticError("sealed_store_count")
    run_directory = run_directories[0]
    if run_directory.is_symlink() or not run_directory.is_dir():
        raise Item32DiagnosticError("sealed_store_metadata")
    database = run_directory / "task-store" / "hot_keywords.db"
    metadata = os.lstat(database)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size < 1
    ):
        raise Item32DiagnosticError("sealed_store_metadata")
    store_sha256 = _sha256_regular_file(database, max_size=64 * 1024 * 1024)
    if store_sha256 != plan.get("sealed_store_sha256"):
        raise Item32DiagnosticError("sealed_store_digest")
    try:
        connection = sqlite3.connect(
            f"file:{database}?mode=ro&immutable=1", uri=True
        )
        try:
            runs = connection.execute(
                "SELECT status,provider_attempt_count,last_error_code,"
                "snapshot_sha256,snapshot_size FROM xhs_trends_runs"
            ).fetchall()
            attempts = connection.execute(
                "SELECT ordinal,endpoint,status,error_code "
                "FROM xhs_trends_provider_attempts ORDER BY ordinal"
            ).fetchall()
            snapshots = int(
                connection.execute(
                    "SELECT COUNT(*) FROM xhs_trends_snapshot_evidence"
                ).fetchone()[0]
            )
            service = connection.execute(
                "SELECT status,active_run_id,session_blocked "
                "FROM xhs_trends_service_state"
            ).fetchall()
            unsafe_attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM xhs_trends_provider_attempts "
                    "WHERE status IN ('admitted','outcome_unknown')"
                ).fetchone()[0]
            )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise Item32DiagnosticError("sealed_store_read") from exc
    if (
        runs
        != [
            (
                "failed",
                1,
                "trends_provider_attempt_evidence_incomplete",
                "",
                0,
            )
        ]
        or attempts != [(1, "homefeed", "failed", "remote_business_error")]
        or snapshots != 0
        or service != [("idle", None, 0)]
        or unsafe_attempts != 0
        or len(attempts) != payload["provider_calls"]
    ):
        raise Item32DiagnosticError("sealed_store_binding")
    return {
        "admission_sha256": admission_sha256,
        "store_sha256": store_sha256,
    }


def _assert_host_preflight(*, allowed_diagnostic_id: str | None = None) -> None:
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
    state = {}
    for row in raw.splitlines():
        key, separator, value = row.partition("=")
        if not separator or key in state:
            raise Item32DiagnosticError("unit_state")
        state[key] = value
    if state != {
        "ActiveState": "inactive",
        "SubState": "dead",
        "UnitFileState": "disabled",
    }:
        raise Item32DiagnosticError("unit_state")
    diagnostic_ids = {
        value
        for value in _run(
            [
                "docker",
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                "label=com.noteai.task=item32-xhs-diagnostic",
            ]
        ).stdout.decode("ascii").splitlines()
        if value
    }
    expected_diagnostic_ids = (
        {allowed_diagnostic_id} if allowed_diagnostic_id else set()
    )
    if diagnostic_ids != expected_diagnostic_ids:
        raise Item32DiagnosticError("diagnostic_container_present")
    container_filters = (
        ("label=com.noteai.task=item32-readonly", "sealed_container_present"),
        (f"name=^/{FIXED_TRENDS_CONTAINER}$", "fixed_container_present"),
    )
    for filter_value, error_code in container_filters:
        if _run(
            ["docker", "ps", "-aq", "--filter", filter_value]
        ).stdout.strip():
            raise Item32DiagnosticError(error_code)
    if list(EXPORT_ROOT.glob("item32-evidence-*.tar.gz")):
        raise Item32DiagnosticError("sealed_export_present")
    inspection = json.loads(
        _run(["docker", "image", "inspect", IMAGE]).stdout
    )[0]
    if (
        inspection.get("Id") != IMAGE
        or ((inspection.get("Config") or {}).get("Labels") or {}).get(
            "com.noteai.runtime.role"
        )
        != "xhs-http"
    ):
        raise Item32DiagnosticError("image_binding")


def _assert_pre_start(container_id: str) -> None:
    _assert_host_preflight(allowed_diagnostic_id=container_id)


def _create_admission(
    plan_sha256: str,
    sealed_hold_sha256: str,
    sealed_store_sha256: str,
) -> None:
    payload = _json_bytes(
        {
            "schema": ADMISSION_SCHEMA,
            "status": "DISPATCHED",
            "created_at": _utc_now(),
            "plan_sha256": plan_sha256,
            "sealed_hold_sha256": sealed_hold_sha256,
            "sealed_store_sha256": sealed_store_sha256,
            "automatic_retry_count": 0,
            "no_replay": True,
        }
    )
    try:
        descriptor = os.open(
            ADMISSION,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError as exc:
        raise Item32DiagnosticError("diagnostic_already_dispatched") from exc
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


def _finish_admission(
    result: Mapping[str, Any],
    *,
    result_sha256: str | None,
    terminal_status: str,
    cleanup_state: str,
) -> None:
    original = json.loads(_read_regular_root_file(ADMISSION, max_size=16384))
    expected_keys = {
        "schema",
        "status",
        "created_at",
        "plan_sha256",
        "sealed_hold_sha256",
        "sealed_store_sha256",
        "automatic_retry_count",
        "no_replay",
    }
    if (
        set(original) != expected_keys
        or original.get("schema") != ADMISSION_SCHEMA
        or original.get("status") != "DISPATCHED"
        or SHA256.fullmatch(str(original.get("plan_sha256") or "")) is None
        or SHA256.fullmatch(str(original.get("sealed_hold_sha256") or ""))
        is None
        or SHA256.fullmatch(str(original.get("sealed_store_sha256") or ""))
        is None
        or original.get("automatic_retry_count") != 0
        or original.get("no_replay") is not True
        or terminal_status
        not in {"COMPLETE_NO_REPLAY", "HOLD_UNKNOWN", "HOLD_CLEANUP", "HOLD_INTERNAL"}
        or cleanup_state not in CLEANUP_STATES
        or (
            terminal_status in {"COMPLETE_NO_REPLAY", "HOLD_INTERNAL"}
            and cleanup_state != "ABSENT"
        )
        or (
            terminal_status == "HOLD_CLEANUP"
            and cleanup_state == "ABSENT"
        )
        or (
            terminal_status == "COMPLETE_NO_REPLAY"
            and (
                not isinstance(result_sha256, str)
                or SHA256.fullmatch(result_sha256) is None
            )
        )
        or (
            result_sha256 is not None
            and (
                not isinstance(result_sha256, str)
                or SHA256.fullmatch(result_sha256) is None
            )
        )
        or (
            terminal_status == "HOLD_UNKNOWN"
            and result.get("outcome_unknown_count") != 1
        )
        or (
            terminal_status in {"COMPLETE_NO_REPLAY", "HOLD_CLEANUP"}
            and result.get("outcome_unknown_count") != 0
        )
    ):
        raise Item32DiagnosticError("admission_transition")
    original.update(
        {
            "status": terminal_status,
            "finished_at": _utc_now(),
            "provider_call_count": result.get("provider_call_count"),
            "outcome_unknown_count": result.get("outcome_unknown_count"),
            "classification": result.get("classification"),
            "container_cleanup_complete": cleanup_state == "ABSENT",
            "container_residue_state": cleanup_state,
        }
    )
    if result_sha256 is not None:
        original["result_sha256"] = result_sha256
    _atomic_write(ADMISSION, _json_bytes(original))


def _publish_result(candidate: Path = RESULT_CANDIDATE) -> None:
    if RESULT.exists():
        raise Item32DiagnosticError("result_already_present")
    os.replace(candidate, RESULT)
    directory = os.open(WORK_ROOT, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _commit_result(
    output: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    terminal_status: str,
    cleanup_state: str,
) -> str:
    output_bytes = _json_bytes(output)
    result_sha256 = _sha256_bytes(output_bytes)
    _atomic_write(RESULT_CANDIDATE, output_bytes)
    admission_transitioned = False
    try:
        _finish_admission(
            result,
            result_sha256=result_sha256,
            terminal_status=terminal_status,
            cleanup_state=cleanup_state,
        )
        admission_transitioned = True
        _publish_result()
    except Exception:
        if not admission_transitioned:
            RESULT_CANDIDATE.unlink(missing_ok=True)
        raise
    return result_sha256


def _remove_container(name: str) -> str:
    if not name:
        return "ABSENT"
    try:
        _run(["docker", "rm", "-f", name], check=False, stderr_to_null=True)
    except (Item32DiagnosticError, subprocess.TimeoutExpired):
        pass
    try:
        remaining = _run(
            ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]
        ).stdout.strip()
    except (Item32DiagnosticError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    return "PRESENT" if remaining else "ABSENT"


def _container_environment(values: Any) -> dict[str, str]:
    if not isinstance(values, list):
        raise Item32DiagnosticError("container_boundary")
    parsed: dict[str, str] = {}
    for row in values:
        if not isinstance(row, str) or "=" not in row:
            raise Item32DiagnosticError("container_boundary")
        key, value = row.split("=", 1)
        if not key or key in parsed:
            raise Item32DiagnosticError("container_boundary")
        parsed[key] = value
    return parsed


def _validate_container_inspection(
    inspection: Any,
    *,
    executor_path: Path,
    adapter_path: Path,
) -> None:
    if not isinstance(inspection, dict):
        raise Item32DiagnosticError("container_boundary")
    config = inspection.get("Config") or {}
    host = inspection.get("HostConfig") or {}
    environment = _container_environment(config.get("Env") or [])
    required_environment = {
        "NOTEAI_RUNTIME_ROLE": "xhs-http",
        "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
        "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
        "NOTEAI_CLOUD_RUNTIME": "1",
        "NOTEAI_SQLITE_PATH": str(ISOLATED_SQLITE_PATH),
    }
    mounts = inspection.get("Mounts") or []
    actual_mounts = {
        (
            item.get("Type"),
            item.get("Source"),
            item.get("Destination"),
            item.get("RW"),
        )
        for item in mounts
        if isinstance(item, dict)
    }
    expected_mounts = {
        (
            "bind",
            str(adapter_path.resolve()),
            "/app/model/spider_xhs_http.py",
            False,
        ),
        (
            "bind",
            str(executor_path.resolve()),
            "/diagnostic/execute.py",
            False,
        ),
    }
    tmpfs = host.get("Tmpfs") or {}
    tmp_tokens = set(str(tmpfs.get("/tmp") or "").split(","))
    valid_tmp_size = bool({"size=128m", "size=134217728"} & tmp_tokens)
    security = set(host.get("SecurityOpt") or [])
    networks = set(((inspection.get("NetworkSettings") or {}).get("Networks") or {}))
    restart = host.get("RestartPolicy") or {}
    labels = config.get("Labels") or {}
    if (
        inspection.get("Image") != IMAGE
        or config.get("User") != "999:999"
        or labels.get("com.noteai.task") != "item32-xhs-diagnostic"
        or "NOTEAI_XHS_COOKIES_JSON" not in environment
        or not environment["NOTEAI_XHS_COOKIES_JSON"]
        or any(environment.get(key) != value for key, value in required_environment.items())
        or "DATABASE_URL" in environment
        or "NOTEAI_XHS_SERVICE" in environment
        or actual_mounts != expected_mounts
        or len(mounts) != 2
        or any("docker.sock" in str(part) for mount in actual_mounts for part in mount)
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or (host.get("CapAdd") or []) != []
        or host.get("NetworkMode") != "bridge"
        or networks != {"bridge"}
        or host.get("IpcMode") != "private"
        or host.get("Memory") != 268435456
        or host.get("NanoCpus") != 250000000
        or host.get("PidsLimit") != 48
        or security not in (
            {"no-new-privileges"},
            {"no-new-privileges:true"},
        )
        or restart != {"Name": "no", "MaximumRetryCount": 0}
        or set(tmpfs) != {"/tmp"}
        or not {
            "rw",
            "noexec",
            "nosuid",
            "nodev",
            "mode=1777",
            "uid=999",
            "gid=999",
        }.issubset(tmp_tokens)
        or not valid_tmp_size
        or config.get("Entrypoint") != ["python"]
        or config.get("Cmd")
        != ["-EsB", "/diagnostic/execute.py", "--container-runner"]
    ):
        raise Item32DiagnosticError("container_boundary")


def _create_container(
    *,
    name: str,
    executor_path: Path,
    adapter_path: Path,
    cookie_json: str,
) -> str:
    runtime_dir = Path(
        tempfile.mkdtemp(prefix="item32-xhs-diagnostic-", dir="/run")
    )
    os.chmod(runtime_dir, 0o700)
    cookie_env = runtime_dir / "xhs.env"
    _atomic_write(
        cookie_env,
        f"NOTEAI_XHS_COOKIES_JSON={cookie_json}\n".encode("utf-8"),
    )
    command = [
        "docker",
        "create",
        "--pull=never",
        "--name",
        name,
        "--label=com.noteai.task=item32-xhs-diagnostic",
        "--user=999:999",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--restart=no",
        "--network=bridge",
        "--ipc=private",
        "--memory=256m",
        "--cpus=0.25",
        "--pids-limit=48",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777,uid=999,gid=999",
        "--env-file",
        str(cookie_env),
        "--env=NOTEAI_RUNTIME_ROLE=xhs-http",
        "--env=NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http",
        "--env=NOTEAI_XHS_COLLECTION_SUSPENDED=0",
        "--env=NOTEAI_CLOUD_RUNTIME=1",
        f"--env=NOTEAI_SQLITE_PATH={ISOLATED_SQLITE_PATH}",
        "--mount",
        f"type=bind,src={adapter_path},dst=/app/model/spider_xhs_http.py,readonly",
        "--mount",
        f"type=bind,src={executor_path},dst=/diagnostic/execute.py,readonly",
        "--entrypoint=python",
        IMAGE,
        "-EsB",
        "/diagnostic/execute.py",
        "--container-runner",
    ]
    container_id = ""
    try:
        container_id = _run(command, timeout=60).stdout.decode().strip()
        if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
            raise Item32DiagnosticError("container_identity")
        inspection = json.loads(
            _run(["docker", "inspect", container_id]).stdout
        )[0]
        _validate_container_inspection(
            inspection,
            executor_path=executor_path,
            adapter_path=adapter_path,
        )
        return container_id
    finally:
        cookie_env.unlink(missing_ok=True)
        try:
            runtime_dir.rmdir()
        except OSError:
            pass


def _validate_runner_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Item32DiagnosticError("runner_result")
    if set(value) != RESULT_KEYS:
        raise Item32DiagnosticError("runner_result")
    classification = value.get("classification")
    response_received = value.get("response_received")
    status = value.get("http_status")
    payload_shape = value.get("payload_shape")
    success_state = value.get("success_state")
    code_state = value.get("code_state")
    marker = value.get("marker_class")
    data_shape = value.get("data_shape")
    items_shape = value.get("items_shape")
    item_count = value.get("item_count")
    calls = value.get("provider_call_count")
    unknown = value.get("outcome_unknown_count")
    isolated_sqlite_state = value.get("isolated_sqlite_state")
    if (
        classification not in CLASSIFICATIONS
        or type(value.get("owner_gate_required")) is not bool
        or type(response_received) is not bool
        or type(item_count) is not int
        or not 0 <= item_count <= 21
        or type(calls) is not int
        or calls not in {0, 1}
        or type(unknown) is not int
        or unknown not in {0, 1}
        or isolated_sqlite_state
        not in {"INITIALIZED", "NOT_INITIALIZED", "UNKNOWN"}
        or (calls == 1 and isolated_sqlite_state == "NOT_INITIALIZED")
        or (
            isolated_sqlite_state == "UNKNOWN"
            and not (
                calls == 1
                and unknown == 1
                and classification == "UNKNOWN_HOLD"
            )
        )
        or value.get("automatic_retry_count") != 0
        or payload_shape not in {"ABSENT", "OBJECT", "OTHER"}
        or success_state not in {"ABSENT", "TRUE", "FALSE", "OTHER"}
        or code_state not in {"ABSENT", "ACCEPTED", "REJECTED"}
        or marker not in MARKER_CLASSES
        or data_shape not in {"ABSENT", "OBJECT", "OTHER"}
        or items_shape not in {"ABSENT", "LIST", "OTHER"}
    ):
        raise Item32DiagnosticError("runner_result")

    expected_gate_required, expected_gate_kind = _owner_gate(classification)
    if (
        value["owner_gate_required"] is not expected_gate_required
        or value.get("owner_gate_kind") != expected_gate_kind
        or (items_shape != "LIST" and item_count != 0)
        or (items_shape == "LIST" and data_shape != "OBJECT")
        or (data_shape != "OBJECT" and items_shape != "ABSENT")
        or (
            payload_shape != "OBJECT"
            and (
                success_state != "ABSENT"
                or code_state != "ABSENT"
                or data_shape != "ABSENT"
                or items_shape != "ABSENT"
                or item_count != 0
            )
        )
    ):
        raise Item32DiagnosticError("runner_result")

    if response_received:
        if (
            type(status) is not int
            or not 100 <= status <= 599
            or calls != 1
            or unknown != 0
            or isolated_sqlite_state != "INITIALIZED"
            or payload_shape == "ABSENT"
        ):
            raise Item32DiagnosticError("runner_result")
        marker_classifications = {
            "ACCOUNT_ACCESS": "ACCOUNT_ACCESS_REVIEW_REQUIRED",
            "RISK_CONTROL": "RISK_CONTROL_REVIEW_REQUIRED",
            "INTERACTIVE_VERIFICATION": (
                "INTERACTIVE_VERIFICATION_REQUIRED"
            ),
            "LOGIN": "LOGIN_REQUIRED",
            "COOLDOWN": "COOLDOWN_HOLD",
        }
        expected_classification = marker_classifications.get(marker)
        if expected_classification is None:
            if status == 401:
                expected_classification = "LOGIN_REQUIRED"
            elif status == 429:
                expected_classification = "COOLDOWN_HOLD"
            elif status == 403:
                expected_classification = "ACCESS_REVIEW_REQUIRED"
            elif status in {400, 404, 405, 415, 422}:
                expected_classification = "REQUEST_CONTRACT_REJECTION"
            elif 500 <= status <= 599:
                expected_classification = "PROVIDER_SERVER_REJECTION"
            elif not 200 <= status <= 299:
                expected_classification = "REMOTE_HTTP_REJECTION"
            elif payload_shape != "OBJECT":
                expected_classification = "ENGINEERING_RESPONSE_SCHEMA"
            elif success_state == "OTHER":
                expected_classification = "ENGINEERING_RESPONSE_SCHEMA"
            elif success_state == "FALSE" or code_state == "REJECTED":
                expected_classification = "ENGINEERING_KNOWN_REJECTION"
            elif (
                data_shape != "OBJECT"
                or items_shape != "LIST"
                or item_count > 20
            ):
                expected_classification = "ENGINEERING_RESPONSE_SCHEMA"
            else:
                expected_classification = "SUCCESS_SHAPE"
        if classification != expected_classification:
            raise Item32DiagnosticError("runner_result")
    else:
        if (
            status is not None
            or payload_shape != "ABSENT"
            or success_state != "ABSENT"
            or code_state != "ABSENT"
            or marker != "NONE"
            or data_shape != "ABSENT"
            or items_shape != "ABSENT"
            or item_count != 0
        ):
            raise Item32DiagnosticError("runner_result")
        if calls == 1:
            if unknown != 1 or classification != "UNKNOWN_HOLD":
                raise Item32DiagnosticError("runner_result")
        elif (
            unknown != 0
            or classification
            not in {
                "LOGIN_REQUIRED",
                "INTERACTIVE_VERIFICATION_REQUIRED",
                "COOLDOWN_HOLD",
                "ENGINEERING_LOCAL_REJECTION",
            }
        ):
            raise Item32DiagnosticError("runner_result")
    return value


def _assert_runner_output_secret_free(
    raw: bytes, secret_values: Mapping[str, str]
) -> None:
    if not 1 <= len(raw) <= 8192:
        raise Item32DiagnosticError("runner_output_size")
    needles = [value for value in secret_values.values() if len(value) >= 8]
    try:
        cookies = json.loads(secret_values["NOTEAI_XHS_COOKIES_JSON"])
        needles.extend(
            str(cookie.get("value") or "")
            for cookie in cookies
            if isinstance(cookie, dict)
            and len(str(cookie.get("value") or "")) >= 8
        )
    except (KeyError, TypeError, ValueError):
        raise Item32DiagnosticError("secret_shape")
    for needle in needles:
        if needle.encode("utf-8") in raw:
            raise Item32DiagnosticError("runner_output_secret")


def _host_main(plan_path: Path, adapter_path: Path) -> int:
    if os.geteuid() != 0:
        raise Item32DiagnosticError("root_required")
    executor_path = Path(__file__).resolve()
    _assert_staged_source(executor_path)
    _assert_staged_source(adapter_path.resolve())
    _assert_staged_source(plan_path.resolve())
    plan, plan_sha256 = _load_plan(
        plan_path.resolve(), executor_path, adapter_path.resolve()
    )
    _ensure_work_root()
    lock = _acquire_lock()
    sealed_lock = -1
    container_name = ""
    admission_created = False
    admission_finished = False
    network_dispatch_started = False
    cleanup_attempted = False
    cleanup_state = "ABSENT"
    result: dict[str, Any] | None = None
    try:
        if ADMISSION.exists() or RESULT.exists() or RESULT_CANDIDATE.exists():
            raise Item32DiagnosticError("diagnostic_already_dispatched")
        sealed_lock = _acquire_sealed_executor_lock()
        sealed = _verify_sealed_hold(plan)
        _assert_host_preflight()
        secret_values = _read_secret_values()
        _create_admission(
            plan_sha256,
            sealed["admission_sha256"],
            sealed["store_sha256"],
        )
        admission_created = True
        container_name = f"noteai-item32-diagnostic-{uuid.uuid4().hex[:12]}"
        container_id = _create_container(
            name=container_name,
            executor_path=executor_path,
            adapter_path=adapter_path.resolve(),
            cookie_json=secret_values["NOTEAI_XHS_COOKIES_JSON"],
        )
        _assert_pre_start(container_id)
        cleanup_complete = True
        try:
            network_dispatch_started = True
            completed = _run(
                ["docker", "start", "-a", container_id],
                timeout=30,
                check=False,
                stderr_to_null=True,
            )
            _assert_runner_output_secret_free(completed.stdout, secret_values)
            lines = [
                line
                for line in completed.stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
            if completed.returncode != 0 or len(lines) != 1:
                result = classify_no_response(
                    request_started=True,
                    adapter_code="container_start_unknown",
                    isolated_sqlite_state="UNKNOWN",
                )
            else:
                try:
                    result = _validate_runner_result(json.loads(lines[0]))
                except (json.JSONDecodeError, Item32DiagnosticError):
                    result = classify_no_response(
                        request_started=True,
                        adapter_code="runner_output_unknown",
                        isolated_sqlite_state="UNKNOWN",
                    )
        except (subprocess.TimeoutExpired, UnicodeDecodeError):
            result = classify_no_response(
                request_started=True,
                adapter_code="container_outcome_unknown",
                isolated_sqlite_state="UNKNOWN",
            )
        finally:
            cleanup_state = _remove_container(container_name)
            cleanup_attempted = True
            cleanup_complete = cleanup_state == "ABSENT"
        if result is None:
            raise Item32DiagnosticError("runner_result_missing")
        result = _validate_runner_result(result)
        if result["outcome_unknown_count"] == 1:
            terminal_status = "HOLD_UNKNOWN"
            output_status = "DIAGNOSTIC_HOLD_UNKNOWN_NO_CREDIT"
        elif not cleanup_complete:
            terminal_status = "HOLD_CLEANUP"
            output_status = "DIAGNOSTIC_HOLD_CLEANUP_NO_CREDIT"
        else:
            terminal_status = "COMPLETE_NO_REPLAY"
            output_status = "DIAGNOSTIC_COMPLETE_NO_CREDIT"
        output = {
            "schema": SCHEMA,
            "item": 32,
            "status": output_status,
            "readiness_credit": False,
            "diagnostic_only": True,
            "observed_at": _utc_now(),
            "plan_sha256": plan_sha256,
            "executor_sha256": plan["outer_executor_sha256"],
            "adapter_source_sha256": plan["adapter_source_sha256"],
            "existing_image_config_sha256": IMAGE_CONFIG_SHA256,
            "existing_registry_manifest_sha256": IMAGE_MANIFEST_SHA256,
            "existing_registry_manifest_provenance": (
                "HISTORICAL_SEALED_PLAN_ONLY"
            ),
            "sealed_hold_sha256": sealed["admission_sha256"],
            "sealed_store_sha256": sealed["store_sha256"],
            "request_profile": {
                "endpoint": "/api/sns/web/v1/homefeed",
                "category": "homefeed_recommend",
                "max_pages": 1,
                "max_items": 20,
                "user_agent_sha256": _sha256_bytes(
                    SIGNER_USER_AGENT.encode("ascii")
                ),
                "timeout_seconds": 20,
                "follow_redirects": False,
            },
            "result": result,
            "isolated_sqlite_configured": True,
            "isolated_sqlite_state": result["isolated_sqlite_state"],
            "sealed_prior_provider_call_count": 1,
            "cumulative_provider_call_count": 1
            + result["provider_call_count"],
            "production_database_queries": 0,
            "production_database_writes": 0,
            "cloud_resource_mutations": 0,
            "postpaid_resources_started": 0,
            "automatic_retry_count": 0,
            "original_executor_replayed": False,
            "container_cleanup_complete": cleanup_complete,
            "container_residue_state": cleanup_state,
            "secret_values_recorded": False,
        }
        _commit_result(
            output,
            result,
            terminal_status=terminal_status,
            cleanup_state=cleanup_state,
        )
        admission_finished = True
        print(
            "ITEM32_XHS_DIAGNOSTIC "
            + json.dumps(output, sort_keys=True, separators=(",", ":"))
        )
        return 0 if cleanup_state == "ABSENT" else 1
    except Exception:
        if container_name and not cleanup_attempted:
            cleanup_state = _remove_container(container_name)
            cleanup_attempted = True
        if admission_created and not admission_finished:
            preserved = result or classify_no_response(
                request_started=network_dispatch_started,
                adapter_code="host_execution_failure",
                isolated_sqlite_state=(
                    "UNKNOWN"
                    if network_dispatch_started
                    else "NOT_INITIALIZED"
                ),
            )
            try:
                preserved = _validate_runner_result(preserved)
                if preserved["outcome_unknown_count"] == 1:
                    hold_status = "HOLD_UNKNOWN"
                elif cleanup_state != "ABSENT":
                    hold_status = "HOLD_CLEANUP"
                else:
                    hold_status = "HOLD_INTERNAL"
                _finish_admission(
                    preserved,
                    result_sha256=None,
                    terminal_status=hold_status,
                    cleanup_state=cleanup_state,
                )
                admission_finished = True
            except Exception:
                pass
        raise
    finally:
        if sealed_lock >= 0:
            os.close(sealed_lock)
        os.close(lock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one no-credit Item32 XHS diagnostic."
    )
    parser.add_argument("--container-runner", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--adapter-source", type=Path)
    args = parser.parse_args(argv)
    if args.container_runner:
        return _container_runner()
    if args.plan is None or args.adapter_source is None:
        raise Item32DiagnosticError("arguments")
    return _host_main(args.plan, args.adapter_source)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Item32DiagnosticError as exc:
        print(f"ITEM32_XHS_DIAGNOSTIC_REJECTED code={exc.code}", file=sys.stderr)
        raise SystemExit(1)
