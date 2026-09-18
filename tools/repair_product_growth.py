#!/usr/bin/env python3
"""Explicit derived-only growth repair. Default: enforced read-only preview.

The private report is fsynced JSONL: its pre-transaction and per-user records
survive an uncertain commit. Never replay a task or use this command to infer a
missing generation from usage. No schema initialization or external calls.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
_USER_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class PrivateReport:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute() or not self.path.parent.is_dir():
            raise ValueError("private_report_path_invalid")
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.fd, 0o600)
        self.hash = hashlib.sha256()
        self.bytes = 0
        parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)

    def append(self, value):
        raw = canonical(value) + b"\n"
        view = memoryview(raw)
        while view:
            written = os.write(self.fd, view)
            if written <= 0:
                raise OSError("private_report_write_failed")
            view = view[written:]
        os.fsync(self.fd)
        self.hash.update(raw)
        self.bytes += len(raw)

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


@contextmanager
def database_transaction(db_module, *, write=False):
    """Enforce dry-run read-only on the actual database, not just in Python."""
    postgres = db_module.using_postgres()
    if postgres or write:
        connection = db_module.get_conn()
    else:
        # Do not use db.get_conn(): its SQLite setup can create a file and set WAL.
        source = Path(db_module._DB_PATH).resolve(strict=True)
        connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
    try:
        if postgres:
            connection.execute("BEGIN" if write else "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        else:
            if not write:
                connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        storage = db_module.Transaction(connection, postgres)
        if not write:
            proof = storage.fetchone("SHOW transaction_read_only" if postgres else "PRAGMA query_only")
            observed = list(dict(proof).values())[0]
            if observed != ("on" if postgres else 1):
                raise ValueError("database_readonly_not_enforced")
        yield storage
        if write:
            connection.commit()
        else:
            connection.rollback()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def source_snapshot(storage, user_id):
    """Hash original source rows in RAM. Export only counts and row identities."""
    queries = {
        "notes": "SELECT id,user_id,domain,score,grade,source,parent_id,version,created_at FROM notes WHERE user_id=? ORDER BY id",
        "diagnoses": "SELECT id,user_id,domain,ces_percentile,grade,diagnosis_json,created_at FROM saved_diagnoses WHERE user_id=? ORDER BY id",
        "generation_tasks": "SELECT c.id,c.user_id,c.note_id,c.generate_ctx_json,r.status,r.complete_applied,r.refund_applied FROM chat_sessions c JOIN idempotency_requests r ON r.id=c.id AND r.user_id=c.user_id WHERE c.user_id=? AND r.operation='generate' ORDER BY c.id",
        "growth": "SELECT id,user_id,note_id,score,grade,domain,action,recorded_at FROM growth_records WHERE user_id=? ORDER BY id",
        "achievements": "SELECT id,user_id,memory_type,content,source_note_id,created_at,updated_at FROM user_memories WHERE user_id=? AND memory_type='achievement' ORDER BY id",
    }
    result = {}
    for kind, query in queries.items():
        rows = [dict(row) for row in storage.fetchall(query, (user_id,))]
        result[kind] = {"count": len(rows), "rows_sha256": digest(rows), "ids": [row["id"] for row in rows]}
    return dict(sources=result, source_digest=digest(result))


def _scope(storage, user_ids, all_eligible):
    if bool(user_ids) == bool(all_eligible):
        raise ValueError("exactly_one_user_scope_required")
    if user_ids:
        if any(not isinstance(value, str) or not _USER_ID.fullmatch(value) for value in user_ids):
            raise ValueError("user_scope_invalid")
        return sorted(set(user_ids))
    rows = storage.fetchall(
        "SELECT u.id FROM users u WHERE u.deletion_requested_at IS NULL AND ("
        "EXISTS(SELECT 1 FROM notes n WHERE n.user_id=u.id) OR "
        "EXISTS(SELECT 1 FROM saved_diagnoses d WHERE d.user_id=u.id) OR "
        "EXISTS(SELECT 1 FROM growth_records g WHERE g.user_id=u.id)) ORDER BY u.id")
    ids = [row["id"] for row in rows]
    if any(not _USER_ID.fullmatch(value) for value in ids):
        raise ValueError("user_scope_invalid")
    return ids


def run_repair(*, transaction, growth, report, user_ids=None, all_eligible=False, apply=False, now=None):
    """Injectable core. One isolated transaction per user; no automatic retry."""
    now = now or (lambda: datetime.now(timezone.utc).isoformat())
    report.append(dict(schema="noteai.product_growth_repair.v1", event="started", mode="apply" if apply else "dry_run",
                       observed_at=now(), scope="all_eligible" if all_eligible else "selected_users"))
    with transaction(write=False) as storage:
        selected = _scope(storage, user_ids, all_eligible)
    totals = dict(users_selected=len(selected), users_completed=0, users_unknown=0,
                  recoverable_records=0, inserted_records=0, achievements_added=0)
    for user_id in selected:
        phase = "read_sources"
        try:
            with transaction(write=apply) as storage:
                if apply:
                    growth._write_fence(storage, user_id)
                else:
                    user = storage.fetchone("SELECT id FROM users WHERE id=? AND deletion_requested_at IS NULL", (user_id,))
                    if not user:
                        raise ValueError("user_not_eligible")
                before = source_snapshot(storage, user_id)
                projection = growth.project_growth_history(storage, user_id)
                pending = [r for r in projection["records"] if r["record_origin"] == "recoverable"]
                report.append(dict(event="snapshot_before", user_id=user_id, observed_at=now(), **before,
                                   recoverable_count=len(pending), provenance=[
                                       {k: row[k] for k in ("source_type", "source_id", "note_id", "source_recorded_at")}
                                       for row in pending]))
                result = dict(inserted_count=0, achievements=[], repaired=[])
                if apply:
                    phase = "repair"
                    result = growth.repair_growth_history_with_storage(storage, user_id, repaired_at=now())
                after = source_snapshot(storage, user_id)
                # Original notes, reports and task state are immutable to this tool.
                if any(before["sources"][key] != after["sources"][key] for key in ("notes", "diagnoses", "generation_tasks")):
                    raise ValueError("original_source_changed")
                phase = "commit" if apply else "readonly_rollback"
            report.append(dict(event="user_completed", user_id=user_id, completed_at=now(),
                               state="DERIVED_RECORDS_APPLIED" if apply else "READONLY_PREVIEW",
                               before_digest=before["source_digest"], after_digest=after["source_digest"],
                               recoverable_count=len(pending), inserted_count=result["inserted_count"],
                               achievements_added=len(result["achievements"]), repairs=result["repaired"]))
            totals["users_completed"] += 1
            totals["recoverable_records"] += len(pending)
            totals["inserted_records"] += result["inserted_count"]
            totals["achievements_added"] += len(result["achievements"])
        except Exception:
            # Never print exception text, SQL, source JSON or connection details.
            totals["users_unknown"] += 1
            report.append(dict(event="user_unconfirmed", user_id=user_id, observed_at=now(), phase=phase,
                               state="OUTCOME_UNCONFIRMED_READBACK_ONLY" if apply else "READONLY_INSPECTION_FAILED",
                               automatic_retry_count=0))
    state = "PARTIAL_UNKNOWN_READBACK_ONLY" if totals["users_unknown"] else "APPLIED" if apply else "DRY_RUN_COMPLETE"
    summary = dict(state=state, **totals, scope_sha256=digest(selected), provider_calls=0, automatic_retry_count=0)
    report.append(dict(event="finished", observed_at=now(), **summary))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", action="append")
    scope.add_argument("--all-eligible", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Explicitly persist only derived growth and missing achievements")
    parser.add_argument("--report", type=Path, required=True, help="New absolute private JSONL report path; never overwritten")
    args = parser.parse_args(argv)
    report = None
    try:
        report = PrivateReport(args.report)
        sys.path.insert(0, str(ROOT / "model"))
        import db
        import growth_history
        def transaction(*, write=False):
            return database_transaction(db, write=write)
        summary = run_repair(transaction=transaction, growth=growth_history, report=report,
                             user_ids=args.user_id, all_eligible=args.all_eligible, apply=args.apply)
        summary.update(report_bytes=report.bytes, report_sha256=report.hash.hexdigest())
        report.close()
        print(json.dumps(summary, sort_keys=True))
        return 2 if summary["users_unknown"] else 0
    except Exception:
        print(json.dumps({"state": "REPAIR_NOT_CONFIRMED_READBACK_ONLY", "automatic_retry_count": 0}))
        return 2
    finally:
        if report is not None:
            try:
                report.close()
            except OSError:
                pass  # Do not expose OS error details after an unconfirmed run.


if __name__ == "__main__":
    raise SystemExit(main())
