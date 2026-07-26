"""Versioned archive retention metadata for user-created NoteAI content."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import hashlib
import re
import uuid

import db


CONTRACT_VERSION = "first-launch-2026-07-25"
FREE_ACTIVE_DAYS = 7
FREE_RECOVERY_DAYS = 7
BACKUP_CLEAR_DAYS = 30
_CONTENT_TYPES = {"note", "diagnosis"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _deadline(value: str | None) -> datetime | None:
    return db._parse_retention_deadline_clock(value)


def _content_created_clock(value: str | None) -> datetime:
    if value is None:
        return _now()
    created = db._parse_retention_source_clock(value)
    if created is None:
        raise ValueError("invalid retention content clock")
    return created


def _storage_uses_postgres(storage: Any) -> bool:
    return bool(getattr(storage, "postgres", db.using_postgres()))


def lock_user_write_fence_with_storage(
    storage: Any,
    user_id: str,
    *,
    lock_row: bool = True,
    allow_deletion_requested: bool = False,
) -> dict[str, Any]:
    """Acquire the canonical per-user write fence before lower-level locks."""
    postgres = _storage_uses_postgres(storage)
    if postgres:
        storage.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            (f"noteai:user-write:{user_id}",),
        )
    row = storage.fetchone(
        "SELECT id,deletion_requested_at FROM users WHERE id=?"
        + (" FOR UPDATE" if postgres and lock_row else ""),
        (user_id,),
    )
    if not row or (row["deletion_requested_at"] and not allow_deletion_requested):
        raise ValueError("账号不可写入")
    return dict(row)


def assert_user_writable_with_storage(
    storage: Any,
    user_id: str,
    *,
    lock_row: bool = True,
) -> dict[str, Any]:
    """Lock and validate the account before any user-owned business write."""
    return lock_user_write_fence_with_storage(
        storage,
        user_id,
        lock_row=lock_row,
    )


def assert_account_deletion_ready_with_storage(
    storage: Any,
    user_id: str,
) -> dict[str, Any]:
    """Hold the user fence and reject deletion while a live request lease runs."""
    user = assert_user_writable_with_storage(storage, user_id)
    # Local import avoids a module-load cycle: idempotency itself uses this
    # user fence for admission and terminalization.
    import idempotency
    import durable_ai

    durable_ai.settle_unstarted_user_jobs_for_deletion_with_storage(
        storage,
        user_id,
        now=_now(),
    )
    idempotency.settle_expired_requests_for_account_deletion_with_storage(
        storage,
        user_id,
        now=_now(),
    )
    active_tracking = storage.fetchone(
        "SELECT 1 FROM tracked_notes WHERE user_id=? "
        "AND active_attempt_id IS NOT NULL LIMIT 1",
        (user_id,),
    )
    if active_tracking:
        # Provider admission takes the same per-user fence before publishing
        # active_attempt_id. Therefore deletion either wins first (and blocks
        # admission) or sees this durable marker and waits without revoking the
        # account mid-call.
        raise ValueError("active tracking attempt prevents account deletion")
    return user


def _paid_at_creation(
    user_id: str,
    created_at: str | None = None,
    storage: Any = db,
) -> bool:
    created = _content_created_clock(created_at)
    if _storage_uses_postgres(storage):
        row = storage.fetchone(
            "SELECT tier FROM subscriptions "
            "WHERE user_id=? AND tier<>'free' "
            "AND started_at::timestamptz<=?::timestamptz "
            "AND expires_at::timestamptz>?::timestamptz "
            "ORDER BY started_at::timestamptz DESC LIMIT 1",
            (user_id, _iso(created), _iso(created)),
        )
        return bool(row)
    rows = storage.fetchall(
        "SELECT started_at,expires_at FROM subscriptions "
        "WHERE user_id=? AND tier<>'free'",
        (user_id,),
    )
    for row in rows:
        started_at = db._parse_retention_source_clock(row["started_at"])
        expires_at = db._parse_retention_source_clock(row["expires_at"])
        if (
            started_at is not None
            and expires_at is not None
            and started_at <= created < expires_at
        ):
            return True
    return False


def _classification(
    user_id: str,
    created: datetime,
    storage: Any,
) -> dict[str, Any]:
    paid = _paid_at_creation(user_id, _iso(created), storage)
    active_until = None if paid else created + timedelta(days=FREE_ACTIVE_DAYS)
    recovery_until = None if paid else active_until + timedelta(days=FREE_RECOVERY_DAYS)
    purge_after = None if paid else recovery_until + timedelta(days=BACKUP_CLEAR_DAYS)
    return {
        "retention_class": "paid_indefinite" if paid else "free_7d",
        "active_until": _iso(active_until),
        "recovery_until": _iso(recovery_until),
        "purge_after": _iso(purge_after),
    }


def _record_content_with_storage(
    storage: Any,
    content_type: str,
    content_id: str,
    user_id: str,
    *,
    created_at: str | None = None,
) -> None:
    existing = storage.fetchone(
        "SELECT user_id,created_at,contract_version "
        "FROM content_retention WHERE content_type=? AND content_id=?",
        (content_type, content_id),
    )
    if existing is not None:
        if (
            existing["user_id"] != user_id
            or existing["contract_version"] != CONTRACT_VERSION
        ):
            raise ValueError("content retention identity conflict")
        if created_at is not None:
            requested_clock = _content_created_clock(created_at)
            existing_clock = db._parse_retention_source_clock(
                existing["created_at"]
            )
            if (
                existing_clock is None
                or requested_clock != existing_clock
            ):
                raise ValueError(
                    "content retention creation clock conflict"
                )
        return
    created = _content_created_clock(created_at)
    classification = _classification(user_id, created, storage)
    storage.execute(
        "INSERT INTO content_retention("
        "content_type,content_id,user_id,retention_class,active_until,recovery_until,"
        "deleted_at,purge_after,purged_at,created_at,updated_at,contract_version"
        ") VALUES(?,?,?,?,?,?,NULL,?,NULL,?,?,?) "
        "ON CONFLICT(content_type,content_id) DO NOTHING",
        (
            content_type,
            content_id,
            user_id,
            classification["retention_class"],
            classification["active_until"],
            classification["recovery_until"],
            classification["purge_after"],
            _iso(created),
            _iso(_now()),
            CONTRACT_VERSION,
        ),
    )


def record_content(
    content_type: str,
    content_id: str,
    user_id: str,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    if content_type not in _CONTENT_TYPES:
        raise ValueError("unsupported retention content type")
    with db.transaction(write=True) as tx:
        assert_user_writable_with_storage(tx, user_id)
        _record_content_with_storage(
            tx,
            content_type,
            content_id,
            user_id,
            created_at=created_at,
        )
    return status(content_type, content_id, user_id)


def insert_content(
    sql: str,
    params: tuple,
    content_type: str,
    content_id: str,
    user_id: str,
    *,
    created_at: str | None = None,
) -> None:
    """Atomically persist business content and its retention classification."""
    if content_type not in _CONTENT_TYPES:
        raise ValueError("unsupported retention content type")
    with db.transaction(write=True) as tx:
        assert_user_writable_with_storage(tx, user_id)
        tx.execute(sql, params)
        _record_content_with_storage(
            tx,
            content_type,
            content_id,
            user_id,
            created_at=created_at,
        )


def _status_payload(
    item: dict[str, Any],
    now: datetime,
    *,
    primary_exists: bool | None = None,
) -> dict[str, Any]:
    retention_class = item.get("retention_class")
    active_until = _deadline(item.get("active_until"))
    recovery_until = _deadline(item.get("recovery_until"))
    deleted_at = _deadline(item.get("deleted_at"))
    purge_after = _deadline(item.get("purge_after"))
    purged_at = _deadline(item.get("purged_at"))
    valid_paid = (
        retention_class == "paid_indefinite"
        and not item.get("active_until")
        and not item.get("recovery_until")
        and (
            (
                not item.get("deleted_at")
                and not item.get("purge_after")
                and not item.get("purged_at")
            )
            or (
                deleted_at is not None
                and purge_after is not None
                and deleted_at <= purge_after
                and (
                    not item.get("purged_at")
                    or (
                        purged_at is not None
                        and purge_after <= purged_at
                        and purged_at <= now
                        and primary_exists is False
                    )
                )
            )
        )
    )
    valid_free = (
        retention_class == "free_7d"
        and active_until is not None
        and recovery_until is not None
        and purge_after is not None
        and active_until <= recovery_until <= purge_after
        and (
            not item.get("deleted_at")
            or (
                deleted_at is not None
                and deleted_at <= purge_after
            )
        )
        and (
            not item.get("purged_at")
            or (
                purged_at is not None
                and purge_after <= purged_at
                and purged_at <= now
                and primary_exists is False
            )
        )
    )
    valid_lifecycle = valid_paid or valid_free
    if not valid_lifecycle:
        state = "expired"
    elif purged_at is not None:
        state = "purged"
    elif deleted_at is not None:
        state = "deleted"
    elif valid_paid or active_until > now:
        state = "active"
    elif recovery_until > now:
        state = "recovery"
    else:
        state = "expired"
    return {
        "state": state,
        "retention_class": item.get("retention_class"),
        "active_until": item.get("active_until"),
        "recovery_until": item.get("recovery_until"),
        "purge_after": item.get("purge_after"),
        "purged_at": item.get("purged_at"),
        "contract_version": item.get("contract_version") or CONTRACT_VERSION,
    }


def status(
    content_type: str,
    content_id: str,
    user_id: str,
    storage: Any = db,
) -> dict[str, Any]:
    if content_type not in _CONTENT_TYPES:
        return {
            "state": "expired",
            "retention_class": "invalid",
            "contract_version": CONTRACT_VERSION,
        }
    row = storage.fetchone(
        "SELECT * FROM content_retention "
        "WHERE content_type=? AND content_id=? AND user_id=?",
        (content_type, content_id, user_id),
    )
    if not row:
        table = "notes" if content_type == "note" else "saved_diagnoses"
        legacy = storage.fetchone(
            f"SELECT created_at FROM {table} WHERE id=? AND user_id=?",
            (content_id, user_id),
        )
        created = _parse(legacy["created_at"]) if legacy else None
        if created is None:
            return {
                "state": "expired",
                "retention_class": "missing",
                "contract_version": CONTRACT_VERSION,
            }
        inferred = {
            **_classification(user_id, created, storage),
            "purged_at": None,
            "contract_version": CONTRACT_VERSION,
        }
        return _status_payload(inferred, _now())
    table = "notes" if content_type == "note" else "saved_diagnoses"
    primary_exists = storage.fetchone(
        f"SELECT 1 FROM {table} WHERE id=? AND user_id=?",
        (content_id, user_id),
    ) is not None
    return _status_payload(
        dict(row),
        _now(),
        primary_exists=primary_exists,
    )


def is_visible(content_type: str, content_id: str, user_id: str) -> bool:
    return status(content_type, content_id, user_id)["state"] == "active"


def recover(content_type: str, content_id: str, user_id: str) -> dict[str, Any]:
    with db.transaction(write=True) as tx:
        assert_user_writable_with_storage(tx, user_id)
        lock_suffix = " FOR UPDATE" if db.using_postgres() else ""
        row = tx.fetchone(
            "SELECT * FROM content_retention WHERE content_type=? AND content_id=? "
            "AND user_id=?" + lock_suffix,
            (content_type, content_id, user_id),
        )
        if not row or _status_payload(dict(row), _now())["state"] != "recovery":
            raise ValueError("该内容不在可恢复期")
        now = _now()
        active_until = now + timedelta(days=FREE_ACTIVE_DAYS)
        recovery_until = active_until + timedelta(days=FREE_RECOVERY_DAYS)
        purge_after = recovery_until + timedelta(days=BACKUP_CLEAR_DAYS)
        tx.execute(
            "UPDATE content_retention SET active_until=?,recovery_until=?,purge_after=?,"
            "updated_at=? WHERE content_type=? AND content_id=? AND user_id=? "
            "AND deleted_at IS NULL AND purged_at IS NULL",
            (
                _iso(active_until),
                _iso(recovery_until),
                _iso(purge_after),
                _iso(now),
                content_type,
                content_id,
                user_id,
            ),
        )
    return status(content_type, content_id, user_id)


def mark_deleted_with_storage(
    storage: Any,
    content_type: str,
    content_id: str,
    user_id: str,
) -> None:
    assert_user_writable_with_storage(storage, user_id)
    row = storage.fetchone(
        "SELECT content_id FROM content_retention "
        "WHERE content_type=? AND content_id=? AND user_id=?",
        (content_type, content_id, user_id),
    )
    if not row:
        _record_content_with_storage(
            storage,
            content_type,
            content_id,
            user_id,
        )
    now = _now()
    storage.execute(
        "UPDATE content_retention SET deleted_at=?,purge_after=?,updated_at=? "
        "WHERE content_type=? AND content_id=? AND user_id=? "
        "AND deleted_at IS NULL AND purged_at IS NULL",
        (
            _iso(now),
            _iso(now + timedelta(days=BACKUP_CLEAR_DAYS)),
            _iso(now),
            content_type,
            content_id,
            user_id,
        ),
    )


def mark_deleted(content_type: str, content_id: str, user_id: str) -> None:
    with db.transaction(write=True) as tx:
        assert_user_writable_with_storage(tx, user_id)
        mark_deleted_with_storage(tx, content_type, content_id, user_id)


def _note_family_ids_with_storage(
    storage: Any,
    note_id: str,
    user_id: str,
) -> list[str]:
    """Return one version chain using a portable recursive CTE."""
    rows = storage.fetchall(
        "WITH RECURSIVE ancestors(id,parent_id) AS ("
        " SELECT id,parent_id FROM notes WHERE id=? AND user_id=?"
        " UNION ALL"
        " SELECT n.id,n.parent_id FROM notes n JOIN ancestors a ON a.parent_id=n.id"
        " WHERE n.user_id=?"
        "), root(id) AS ("
        " SELECT id FROM ancestors WHERE parent_id IS NULL LIMIT 1"
        "), family(id) AS ("
        " SELECT id FROM root"
        " UNION ALL"
        " SELECT n.id FROM notes n JOIN family f ON n.parent_id=f.id"
        " WHERE n.user_id=?"
        ") SELECT id FROM family",
        (note_id, user_id, user_id, user_id),
    )
    ids = [str(row["id"]) for row in rows]
    return ids or [note_id]


def delete_note_derivatives_with_storage(
    storage: Any,
    note_id: str,
    user_id: str,
) -> None:
    """Remove note-linked copies before the canonical note is detached/purged."""
    family_ids = _note_family_ids_with_storage(storage, note_id, user_id)
    placeholders = ",".join("?" for _ in family_ids)
    storage.execute(
        f"DELETE FROM chat_sessions WHERE user_id=? AND note_id IN ({placeholders})",
        (user_id, *family_ids),
    )
    storage.execute(
        f"DELETE FROM user_memories WHERE user_id=? AND memory_type='context' "
        f"AND (source_note_id IN ({placeholders}) OR source_note_id IS NULL)",
        (user_id, *family_ids),
    )


def recoverable_for_user(user_id: str) -> list[dict[str, Any]]:
    rows = db.fetchall(
        "SELECT content_type,content_id,active_until,recovery_until,contract_version "
        "FROM content_retention WHERE user_id=? AND deleted_at IS NULL "
        "ORDER BY recovery_until ASC",
        (user_id,),
    )
    return [
        {**dict(row), "state": "recovery"}
        for row in rows
        if status(row["content_type"], row["content_id"], user_id)["state"] == "recovery"
    ]


def request_account_deletion(user_id: str) -> dict[str, Any]:
    """Disable primary account access now and queue the approved deletion clocks."""
    now = _now()
    request_id = str(uuid.uuid4())
    primary_delete_by = now + timedelta(hours=24)
    backup_clear_by = now + timedelta(days=BACKUP_CLEAR_DAYS)
    with db.transaction(write=True) as tx:
        return request_account_deletion_with_storage(
            tx,
            user_id,
            now=now,
            request_id=request_id,
            primary_delete_by=primary_delete_by,
            backup_clear_by=backup_clear_by,
        )


def request_account_deletion_with_storage(
    storage: Any,
    user_id: str,
    *,
    now: datetime | None = None,
    request_id: str | None = None,
    primary_delete_by: datetime | None = None,
    backup_clear_by: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    request_id = request_id or str(uuid.uuid4())
    primary_delete_by = primary_delete_by or now + timedelta(hours=24)
    backup_clear_by = backup_clear_by or now + timedelta(days=BACKUP_CLEAR_DAYS)
    assert_account_deletion_ready_with_storage(storage, user_id)
    existing = storage.fetchone(
            "SELECT * FROM account_deletion_requests WHERE user_id=? "
            "AND status IN ('requested','primary_deleted','backup_clear_pending')",
            (user_id,),
        )
    if existing:
        return dict(existing)
    subject_ref = "deleted:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    storage.execute(
            "INSERT INTO account_deletion_requests("
            "id,user_id,subject_ref,requested_at,primary_inaccessible_at,primary_delete_by,"
            "backup_clear_by,status,contract_version"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                user_id,
                subject_ref,
                _iso(now),
                _iso(now),
                _iso(primary_delete_by),
                _iso(backup_clear_by),
                "requested",
                CONTRACT_VERSION,
            ),
        )
    storage.execute(
            "UPDATE users SET deletion_requested_at=? WHERE id=?",
            (_iso(now), user_id),
        )
    storage.execute(
        "UPDATE tracked_notes SET status='account_deletion_pending',"
        "next_check_at=NULL WHERE user_id=?",
        (user_id,),
    )
    storage.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
    return dict(storage.fetchone(
            "SELECT * FROM account_deletion_requests WHERE id=?",
            (request_id,),
        ))


def process_due_content_purges(
    *,
    limit: int = 25,
    now: datetime | None = None,
) -> list[str]:
    """Bounded, idempotent primary purge. Production scheduling is separate."""
    current = now or _now()
    purged: list[str] = []
    postgres = db.using_postgres()
    due_predicate = (
        "purge_after::timestamptz<=?::timestamptz"
        if postgres
        else "noteai_retention_clock_lte(purge_after,?)=1"
    )
    candidates = db.fetchall(
        "SELECT content_type,content_id,user_id FROM content_retention "
        "WHERE purged_at IS NULL AND purge_after IS NOT NULL "
        f"AND {due_predicate} ORDER BY purge_after ASC LIMIT ?",
        (_iso(current), max(1, min(int(limit), 100))),
    )
    for candidate in candidates:
        with db.transaction(write=True) as tx:
            try:
                assert_user_writable_with_storage(tx, candidate["user_id"])
            except ValueError:
                continue
            row = tx.fetchone(
                "SELECT * FROM content_retention WHERE content_type=? "
                "AND content_id=? AND user_id=? AND purged_at IS NULL "
                f"AND purge_after IS NOT NULL AND {due_predicate}"
                + (" FOR UPDATE" if postgres else ""),
                (
                    candidate["content_type"],
                    candidate["content_id"],
                    candidate["user_id"],
                    _iso(current),
                ),
            )
            if not row:
                continue
            content_type = row["content_type"]
            content_id = row["content_id"]
            if content_type == "note":
                delete_note_derivatives_with_storage(
                    tx,
                    content_id,
                    row["user_id"],
                )
                tx.execute("DELETE FROM growth_records WHERE note_id=?", (content_id,))
                tx.execute(
                    "UPDATE tracked_notes SET source_note_id=NULL WHERE source_note_id=?",
                    (content_id,),
                )
                tx.execute(
                    "UPDATE tracked_notes SET source_root_note_id=NULL "
                    "WHERE source_root_note_id=?",
                    (content_id,),
                )
                tx.execute("UPDATE notes SET parent_id=NULL WHERE parent_id=?", (content_id,))
                tx.execute("DELETE FROM notes WHERE id=? AND user_id=?", (
                    content_id,
                    row["user_id"],
                ))
            else:
                tx.execute(
                    "DELETE FROM saved_diagnoses WHERE id=? AND user_id=?",
                    (content_id, row["user_id"]),
                )
            primary_table = (
                "notes" if content_type == "note" else "saved_diagnoses"
            )
            if tx.fetchone(
                f"SELECT 1 FROM {primary_table} WHERE id=? AND user_id=?",
                (content_id, row["user_id"]),
            ) is not None:
                raise RuntimeError(
                    "content purge marker requires primary deletion"
                )
            updated = tx.execute(
                "UPDATE content_retention SET purged_at=?,updated_at=? "
                "WHERE content_type=? AND content_id=? AND purged_at IS NULL",
                (_iso(current), _iso(current), content_type, content_id),
            )
            if int(getattr(updated, "rowcount", 0) or 0) != 1:
                raise RuntimeError("content purge marker transition was not recorded")
            purged.append(f"{content_type}:{content_id}")
    return purged


def process_due_account_deletions(
    *,
    limit: int = 10,
    now: datetime | None = None,
    payload_store: Any = None,
) -> list[str]:
    """Delete primary personal data while retaining pseudonymous audit ledgers."""
    current = now or _now()
    completed: list[str] = []
    postgres = db.using_postgres()
    due_predicate = (
        "primary_delete_by::timestamptz<=?::timestamptz"
        if postgres
        else "primary_delete_by<=?"
    )
    candidates = db.fetchall(
        "SELECT id,user_id FROM account_deletion_requests "
        f"WHERE status='requested' AND {due_predicate} "
        "ORDER BY primary_delete_by ASC LIMIT ?",
        (_iso(current), max(1, min(int(limit), 50))),
    )
    for candidate in candidates:
        user_id = candidate["user_id"]
        if not user_id:
            continue
        # External request/result objects must be erased before the database
        # join that proves their owner is pseudonymized. Admission is already
        # fenced by deletion_requested_at, so no new owner object can race in.
        try:
            import durable_ai

            durable_ai.delete_user_payloads(
                user_id,
                store=payload_store,
                now=current,
            )
        except durable_ai.PayloadUnavailable:
            # Fail closed: keep the deletion request pending and preserve the
            # owner join for a later bounded retry.
            continue
        with db.transaction(write=True) as tx:
            try:
                lock_user_write_fence_with_storage(
                    tx,
                    user_id,
                    allow_deletion_requested=True,
                )
            except ValueError:
                continue
            request = tx.fetchone(
                "SELECT * FROM account_deletion_requests WHERE id=? "
                f"AND user_id=? AND status='requested' AND {due_predicate}"
                + (" FOR UPDATE" if postgres else ""),
                (candidate["id"], user_id, _iso(current)),
            )
            if not request:
                continue
            if durable_ai.has_ready_user_payloads(tx, user_id):
                continue
            subject_ref = request["subject_ref"]
            tx.execute("UPDATE usage_records SET user_id=? WHERE user_id=?", (
                subject_ref,
                user_id,
            ))
            tx.execute("UPDATE credit_transactions SET user_id=? WHERE user_id=?", (
                subject_ref,
                user_id,
            ))
            tx.execute(
                "DELETE FROM ai_operation_admissions "
                "WHERE idempotency_request_id IN ("
                "SELECT id FROM idempotency_requests WHERE user_id=?)",
                (user_id,),
            )
            tx.execute("DELETE FROM user_learn WHERE user_id=?", (user_id,))
            tx.execute("DELETE FROM chat_sessions WHERE user_id=?", (user_id,))
            tx.execute("DELETE FROM growth_records WHERE user_id=?", (user_id,))
            tx.execute("DELETE FROM tracked_notes WHERE user_id=?", (user_id,))
            tx.execute("UPDATE notes SET parent_id=NULL WHERE user_id=?", (user_id,))
            tx.execute(
                "UPDATE account_deletion_requests SET user_id=NULL,status=?,"
                "primary_deleted_at=? WHERE id=?",
                ("backup_clear_pending", _iso(current), request["id"]),
            )
            tx.execute("DELETE FROM users WHERE id=?", (user_id,))
            completed.append(str(request["id"]))
    return completed


def confirm_backup_cleared(request_id: str, evidence_ref: str) -> dict[str, Any]:
    """Record an externally verified backup-clear boundary; never clears backups."""
    evidence = str(evidence_ref or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", evidence):
        raise ValueError("备份清理证据引用格式无效")
    with db.transaction(write=True) as tx:
        lock_suffix = " FOR UPDATE" if db.using_postgres() else ""
        row = tx.fetchone(
            "SELECT * FROM account_deletion_requests WHERE id=?" + lock_suffix,
            (request_id,),
        )
        if not row or row["status"] != "backup_clear_pending":
            raise ValueError("删除请求不在备份确认阶段")
        now = _now()
        tx.execute(
            "UPDATE account_deletion_requests SET status='complete',"
            "backup_cleared_at=?,backup_evidence_ref=? WHERE id=?",
            (_iso(now), evidence, request_id),
        )
        return dict(tx.fetchone(
            "SELECT * FROM account_deletion_requests WHERE id=?",
            (request_id,),
        ))
