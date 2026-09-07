#!/usr/bin/env python3
"""One interactive, loopback-only existing-user submission for approved Item34.

Run on API-F after the owner/DDL/ACL preflight. Credentials stay in memory;
only bounded results go to the existing private execution journal. No retries,
registration, direct SQL, provider calls, redirects, or environment loading.
"""

import argparse
import getpass
import hashlib
import http.client
import json
import sys
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

try:
    from .run_item34_tracking_durable import Journal
except ImportError:
    from run_item34_tracking_durable import Journal


NOTE_ID = "6a7954010000000026034707"
NOTE_URL = "https://www.xiaohongshu.com/explore/" + NOTE_ID
DEADLINE = datetime.fromisoformat("2026-09-07T22:30:38+08:00")
ERROR_CODES = {"old_window_closed", "target_readback_unknown", "target_readback_invalid",
               "target_not_unique", "login_failed", "login_unknown", "managed_result_unknown",
               "credentials_empty_no_request"}


def safe_error(exc):
    return str(exc) if isinstance(exc, ValueError) and str(exc) in ERROR_CODES else type(exc).__name__


def hidden_password():
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass("NoteAI password (hidden, never saved): ")


def before_deadline():
    if datetime.now(timezone.utc) >= DEADLINE:
        raise ValueError("old_window_closed")


def request(method, path, body=None, token=None):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=20)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            return None, {}
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            value = {}
        return response.status, value if isinstance(value, dict) else {}
    except (OSError, http.client.HTTPException):
        return None, {}
    finally:
        connection.close()


def target_readback(call, token, track_id=None):
    path = "/notes/tracking/" + str(uuid.UUID(track_id)) if track_id else "/notes/tracking"
    status, value = call("GET", path, token=token)
    if status != 200:
        raise ValueError("target_readback_unknown")
    notes = [value] if track_id else value.get("notes")
    if not isinstance(notes, list):
        raise ValueError("target_readback_invalid")
    matches = [row for row in notes if isinstance(row, dict) and row.get("xhs_note_id") == NOTE_ID]
    if len(matches) > 1:
        raise ValueError("target_not_unique")
    if not matches:
        return None
    row = matches[0]
    return {"id": str(uuid.UUID(row["id"])), "xhs_note_id": NOTE_ID,
            "status": row.get("status"), "domain": row.get("domain"),
            "published_at": row.get("published_at"), "submitted_at": row.get("submitted_at"),
            "next_check_at": row.get("next_check_at")}


def submit(username, password, domain, journal, call=request):
    before_deadline()
    journal.write("auth_dispatch", action="password_login", actual_row_mutations=None,
                  count_basis="SOURCE_BOUNDED_NOT_OBSERVED")
    status, login = call("POST", "/auth/login", {"username": username, "password": password})
    password = None
    token = login.get("token")
    outcome = "SUCCEEDED" if status == 200 and isinstance(token, str) and token else (
        "FAILED" if status in (401, 429) else "UNKNOWN")
    journal.write("auth_result", action="password_login", outcome=outcome, http_status=status,
                  direct_row_upper_bound=4 if outcome == "FAILED" else 6,
                  actual_row_mutations=None, count_basis="SOURCE_BOUNDED_NOT_OBSERVED")
    if outcome != "SUCCEEDED":
        raise ValueError("login_" + outcome.lower())
    login.clear()
    row = target_readback(call, token)
    journal.write("managed_preflight", target_note_id=NOTE_ID, target_count=int(row is not None))
    if row is None:
        before_deadline()
        body = {"xhs_url": NOTE_URL, "domain": domain, "published_at": None}
        journal.write("managed_post_dispatch", target_note_id=NOTE_ID, domain=domain,
                      request_sha256=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
        status, result = call("POST", "/notes/track-url", body, token)
        journal.write("managed_post_response", http_status=status,
                      outcome="SUCCEEDED" if status == 200 and result.get("id") else
                      "EXISTING" if status == 409 else "UNKNOWN")
        # Even a missing/failed response never authorizes another POST.
        row = target_readback(call, token, result.get("id") if status == 200 else None)
    if row is None:
        raise ValueError("managed_result_unknown")
    journal.write("managed_readback", row=row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty() or not 1 <= len(args.domain.strip()) <= 32:
        raise SystemExit("interactive_tty_and_owner_domain_required")
    before_deadline()
    journal = Journal(args.journal)
    try:
        username = input("Existing NoteAI username or verified phone: ").strip()
        password = hidden_password()
        if not username or not password:
            raise ValueError("credentials_empty_no_request")
        row = submit(username, password, args.domain.strip(), journal)
        print(json.dumps({"managed_track": row}, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        code = safe_error(exc)
        journal.write("managed_submission_stopped", code=code, replay_allowed=False)
        print("ITEM34_SUBMISSION_STOPPED " + code)
        return 1
    finally:
        journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
