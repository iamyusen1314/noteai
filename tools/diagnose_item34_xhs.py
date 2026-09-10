#!/usr/bin/env python3
"""One separately authorized Item34 detail diagnostic; never a checkpoint.

Run in the frozen XHS image with only the reviewed diagnostic files mounted.
The host must preserve explicit operator stops. This entry does not unlock any
flag, initialize a database, invoke a worker, or write production state.
An existing journal (including a partial one) permits readback only.
"""
from __future__ import annotations

import json
import getpass
import os
import re
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

MODEL = Path(__file__).resolve().parents[1] / "model"
sys.path.insert(0, str(MODEL))

import httpx
import spider_xhs_http as xhs
from security_redaction import sanitize_xhs_response_diagnostics, sanitize_xhs_http_event

NOTE_URL = "https://www.xiaohongshu.com/explore/6a7954010000000026034707"
ENDPOINT = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
JOURNAL = Path("/out/item34-diagnostic.jsonl")
REPAIR_JOURNAL = Path("/out/xhs-repair-batch.jsonl")


class DiagnosticStop(RuntimeError):
    pass


def request_cookie_records(raw: str) -> list:
    """Convert an owner's complete Request Cookie without discarding context."""
    if not isinstance(raw, str) or not raw or len(raw) > 32768 or any(
            ord(char) < 32 or ord(char) > 126 for char in raw):
        raise DiagnosticStop("request_cookie_invalid")
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    records, names = [], set()
    for pair in raw.split(";"):
        name, separator, value = pair.strip().partition("=")
        if (not separator or not value or name in names
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)):
            raise DiagnosticStop("request_cookie_invalid")
        names.add(name)
        records.append({"name": name, "value": value, "domain": ".xiaohongshu.com"})
    if not {"a1", "web_session"}.issubset(names):
        raise DiagnosticStop("request_cookie_auth_missing")
    return records


def stage_session() -> int:
    """TTY-only task candidate; leave managed env, history and DB untouched."""
    if not sys.stdin.isatty() or not sys.stderr.isatty() or os.geteuid() != 0:
        raise DiagnosticStop("private_root_terminal_required")
    path = Path("/out/session-candidate.env")
    if path.exists() or path.is_symlink():
        raise DiagnosticStop("existing_session_candidate_readback_only")
    print("Paste complete Request Cookie from the existing owned-account browser. Input is hidden.", flush=True)
    records = request_cookie_records(getpass.getpass("Request Cookie (hidden): "))
    # Optional state is not a prerequisite; blank means no added signing state.
    print("Optional existing webSsk JSON; press Enter if unavailable. Do not invent it.", flush=True)
    raw_ssk = getpass.getpass("webSsk JSON (hidden, optional): ")
    from spider_xhs_v5 import session_signing_storage
    storage = session_signing_storage(raw_ssk)
    rows = {"NOTEAI_XHS_COOKIES_JSON": records}
    if storage:
        rows["NOTEAI_XHS_WEB_SSK_JSON"] = storage["webSsk"]
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        for name, value in rows.items():
            handle.write(name + "=" + json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print(json.dumps({"status": "SESSION_CANDIDATE_STAGED_NOT_APPLIED", "cookie_count": len(records),
        "optional_signing_state_present": bool(storage), "xhs_requests": 0, "business_writes": 0}), flush=True)
    return 0


def configure_readonly_database() -> None:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn.lower().startswith(("postgres://", "postgresql://")):
        raise DiagnosticStop("production_readonly_database_required")
    parts = urlsplit(dsn)
    query = parse_qsl(parts.query, keep_blank_values=True)
    options = dict(query).get("options", os.environ.get("PGOPTIONS", ""))
    query = [(key, value) for key, value in query if key not in {"options", "connect_timeout"}]
    query.extend([
        ("options", options + " -c default_transaction_read_only=on -c statement_timeout=5000"),
        ("connect_timeout", "5"),
    ])
    # Keep URI form: NoteAI's existing DB routing deliberately rejects keyword DSNs.
    # libpq URI query uses percent decoding, not HTML form '+' decoding.
    os.environ["DATABASE_URL"] = urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))


def readonly_safety() -> dict:
    import db

    if not db.using_postgres():
        raise DiagnosticStop("production_readonly_database_required")
    conn = db.get_conn()
    try:
        identity = conn.execute(
            "SELECT current_user AS role, current_setting('transaction_read_only') AS readonly"
        ).fetchone()
        if identity["role"] != "noteai_xhs_tracking" or identity["readonly"] != "on":
            raise DiagnosticStop("readonly_identity_not_verified")
        row = conn.execute(
            "SELECT value_json, is_secret FROM system_settings WHERE key='xhs_collection_safety'"
        ).fetchone()
        if row is None:
            return {"record_present": False, "session_blocked": False, "transaction_read_only": True}
        if row["is_secret"]:
            raise DiagnosticStop("safety_record_not_readable")
        raw = row["value_json"]
        state = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(state, dict) or type(state.get("session_blocked")) is not bool:
            raise DiagnosticStop("safety_record_invalid")
        if state["session_blocked"]:
            raise DiagnosticStop("persistent_session_stop")
        return {"record_present": True, "session_blocked": False, "transaction_read_only": True}
    finally:
        conn.close()


class OneRequest:
    def __init__(self, append, safety=readonly_safety):
        self.append = append
        self.safety = safety
        self.admitted = 0
        self.http_status = None

    def before(self, request: httpx.Request) -> None:
        if self.admitted or request.method != "POST" or str(request.url) != ENDPOINT:
            raise DiagnosticStop("additional_or_unapproved_request_blocked")
        if xhs.collection_suspended() or os.environ.get("NOTEAI_XHS_SERVICE") == "trends":
            raise DiagnosticStop("operator_stop_or_wrong_service")
        body = json.loads(request.content)
        if body != {
            "source_note_id": NOTE_URL.rsplit("/", 1)[1],
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"}, "xsec_source": "pc_search", "xsec_token": "",
        }:
            raise DiagnosticStop("request_contract_changed")
        safety = self.safety()
        # Reserve before send. A crash from this point is UNKNOWN, never replay.
        self.admitted = 1
        self.append({"event": "dispatch_intent", "provider_admissions": 1, "safety": safety})

    def received(self, response: httpx.Response) -> None:
        self.http_status = response.status_code
        self.append({"event": "response_headers_received", "http_status": response.status_code})


def run(append, *, transport=None, adapter_factory=xhs.SpiderXHSHTTPAdapter,
        safety=readonly_safety) -> dict:
    guard = OneRequest(append, safety)
    result = {"event": "result", "outcome": "STOPPED_BEFORE_REQUEST", "provider_admissions": 0,
              "automatic_retries": 0, "qualifying_snapshot": False, "business_writes": 0}
    adapter = None
    try:
        if sys.version_info[:2] != (3, 11):
            raise DiagnosticStop("python_311_required")
        if os.environ.get("NOTEAI_XHS_SERVICE") != "tracking" or xhs.collection_suspended():
            raise DiagnosticStop("operator_stop_or_wrong_service")
        append({"event": "safety_readback", "safety": safety()})
        with httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0),
            timeout=20, follow_redirects=False, trust_env=False,
            event_hooks={"request": [guard.before], "response": [guard.received]},
        ) as client:
            adapter = adapter_factory(client=client)
            adapter.note_detail(NOTE_URL)  # Response content remains in memory only.
        result["outcome"] = "RESPONSE_ACCEPTED_NOT_A_SNAPSHOT"
    except xhs.XHSAdapterError as exc:
        result["error_code"] = exc.code
        result["outcome"] = (
            "REMOTE_REJECTED" if guard.http_status is not None and exc.code != "network_error"
            else "UNKNOWN" if guard.admitted else "STOPPED_BEFORE_REQUEST"
        )
    except DiagnosticStop as exc:
        result["error_code"] = str(exc)  # Fixed local codes only, never upstream text.
        result["outcome"] = "UNKNOWN" if guard.admitted else "STOPPED_BEFORE_REQUEST"
    except BaseException:
        result["error_code"] = "diagnostic_internal_error"
        result["outcome"] = "UNKNOWN" if guard.admitted else "STOPPED_BEFORE_REQUEST"
    result["provider_admissions"] = guard.admitted
    result["response_received"] = guard.http_status is not None
    result["incremental_cost"] = "UNKNOWN_NOT_ZERO" if guard.admitted else "NO_PROVIDER_ADMISSION"
    diagnostics = sanitize_xhs_response_diagnostics(
        adapter.last_response_diagnostics if adapter else None,
    )
    if guard.http_status is not None:
        diagnostics["http_status"] = guard.http_status
    result["response_diagnostics"] = diagnostics
    append(result)
    return result


def run_repair(append, *, adapter_factory=xhs.SpiderXHSHTTPAdapter, safety=readonly_safety) -> dict:
    """One finite v5 experiment: DSL/session/detail, with fsync before each send.

    The caller supplies a fresh exclusive task journal; this never reads/reuses
    the old consumed diagnostic. No worker, initialization DML or safety reset.
    """
    events = []
    adapter = None
    result = {"event": "result", "outcome": "STOPPED_BEFORE_REQUEST", "automatic_retries": 0,
              "qualifying_snapshot": False, "business_writes": 0, "physical_http_requests": 0,
              "provider_detail_admissions": 0, "initialization_requests": 0}

    def observe(value):
        safe = sanitize_xhs_http_event(value)
        if not safe or safe != value:
            raise DiagnosticStop("invalid_http_observation")
        if safe["phase"] == "dispatch":
            sent = [event for event in events if event["phase"] == "dispatch"]
            if len(sent) >= 3 or safe["request_kind"] != ("dsl", "session", "detail")[len(sent)]:
                raise DiagnosticStop("unexpected_http_sequence")
            if safe["sequence"] != len(sent) + 1:
                raise DiagnosticStop("unexpected_http_sequence")
            if xhs.collection_suspended() or os.environ.get("NOTEAI_XHS_SERVICE") != "tracking":
                raise DiagnosticStop("operator_stop_or_wrong_service")
            safety()  # Current persistent state checked before every physical request.
        append({"event": "xhs_http", "observation": safe})
        events.append(safe)

    try:
        if sys.version_info[:2] != (3, 11):
            raise DiagnosticStop("python_311_required")
        if os.environ.get("NOTEAI_XHS_PROTOCOL") != "pc_v5":
            raise DiagnosticStop("v5_protocol_required")
        if os.environ.get("NOTEAI_XHS_SERVICE") != "tracking" or xhs.collection_suspended():
            raise DiagnosticStop("operator_stop_or_wrong_service")
        append({"event": "safety_readback", "safety": safety()})
        adapter = adapter_factory(http_observer=observe)
        adapter.note_detail(NOTE_URL)
        if adapter.last_owned_metrics is None:
            raise DiagnosticStop("owned_metrics_not_verified")
        result.update(outcome="OWNED_READ_VERIFIED_NOT_A_SNAPSHOT", owned_note_verified=True,
                      metrics=adapter.last_owned_metrics)
    except xhs.XHSAdapterError as exc:
        result["error_code"] = exc.code
    except DiagnosticStop as exc:
        result["error_code"] = str(exc)
    except BaseException:
        result["error_code"] = "diagnostic_internal_error"
    sent = [event for event in events if event["phase"] == "dispatch"]
    result["physical_http_requests"] = len(sent)
    result["provider_detail_admissions"] = sum(event["request_kind"] == "detail" for event in sent)
    result["initialization_requests"] = sum(event["request_kind"] != "detail" for event in sent)
    if sent and result["outcome"] == "STOPPED_BEFORE_REQUEST":
        result["outcome"] = "UNKNOWN" if events[-1]["phase"] != "response" else "READ_NOT_VERIFIED"
    result["incremental_cost"] = "UNKNOWN_NOT_ZERO" if sent else "NO_PROVIDER_ADMISSION"
    result["response_diagnostics"] = sanitize_xhs_response_diagnostics(
        adapter.last_response_diagnostics if adapter else None)
    append(result)
    return result


def main() -> int:
    if sys.argv[1:] == ["--stage-session"]:
        return stage_session()
    repair = sys.argv[1:] == ["--repair-v5"]
    if sys.argv[1:] and not repair:
        raise DiagnosticStop("unsupported_mode")
    os.umask(0o077)
    journal = REPAIR_JOURNAL if repair else JOURNAL
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        directory = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

        def append(value):
            record = {**value, "at": datetime.now(timezone.utc).isoformat()}
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        if repair:
            append({"event": "repair_started", "request_limit": 3, "automatic_retries": 0,
                    "purpose": "v5_cookie_initialization_and_owned_read_not_observation",
                    "upstream_commit": "7077c88f82771f547cc1afdadaec4025be2355e6"})
        else:
            append({"event": "diagnostic_started", "generation": 1, "request_limit": 1,
                    "purpose": "separate_error_diagnostic_not_24h_retry"})
        try:
            configure_readonly_database()
        except BaseException:
            append({"event": "result", "outcome": "STOPPED_BEFORE_REQUEST",
                    "provider_admissions": 0, "error_code": "readonly_database_setup_failed"})
            return 1
        result = run_repair(append) if repair else run(append)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result["outcome"] in {"RESPONSE_ACCEPTED_NOT_A_SNAPSHOT", "OWNED_READ_VERIFIED_NOT_A_SNAPSHOT"} else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileExistsError:
        print('{"status":"EXISTING_JOURNAL_READBACK_ONLY"}', flush=True)
        sys.exit(2)
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        print('{"status":"STOPPED_RECONCILE_JOURNAL_NO_REPLAY"}', flush=True)
        sys.exit(2)
