"""Growth projections and explicit repair from retained, user-owned records.

Reading never writes. Repair callers must supply an existing write transaction;
no model, provider, billing or task replay is involved. Note/report identifiers,
not text similarity or usage counts, define an event.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone


_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_PREDICTION_ACTIONS = {"diagnose", "analyze", "generate", "chat", "chat_optimize", "chat_select_plan", "manual"}
_PERFORMANCE_ACTIONS = {"url_track", "url_crawl_7d", "url_crawl_3d"}


def _score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 100 else None


def _clock(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _object(value):
    try:
        obj = json.loads(value) if isinstance(value, str) else value
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _visible(storage, kind, identity, user_id, is_visible):
    if is_visible is not None:
        return is_visible(kind, identity, user_id) is True
    import content_retention
    return content_retention.status(kind, identity, user_id, storage=storage)["state"] == "active"


def _event(kind, identity, user_id, note_id, domain, score, grade, action, occurred_at):
    score, occurred_at = _score(score), _clock(occurred_at)
    if not isinstance(identity, str) or not _ID.fullmatch(identity) or score is None or occurred_at is None:
        return None
    return dict(source_type=kind, source_id=identity, user_id=user_id, note_id=note_id,
                domain=domain or "", score=score, grade=grade or "", action=action,
                source_recorded_at=occurred_at)


def load_source_events(storage, user_id, *, is_visible=None):
    """Read metadata only, plus saved result JSON for exact identity/quality checks.

Generated reports need an actually completed claim and matching saved result.
Saved note versions remain valid save events in their own right; this does not
certify a caller-supplied score as an independently verified model prediction.
    """
    notes = {}
    for row in storage.fetchall(
        "SELECT id,user_id,domain,score,grade,source,parent_id,version,created_at FROM notes WHERE user_id=?", (user_id,)
    ):
        row = dict(row)
        if _visible(storage, "note", row["id"], user_id, is_visible):
            notes[row["id"]] = row
    events, represented, claimed_generation_notes = [], set(), set()
    for raw in storage.fetchall(
        "SELECT id,user_id,domain,ces_percentile,grade,diagnosis_json,created_at FROM saved_diagnoses WHERE user_id=?", (user_id,)
    ):
        row = dict(raw)
        if not _visible(storage, "diagnosis", row["id"], user_id, is_visible):
            continue
        data = _object(row["diagnosis_json"])
        if (data.get("quality_failed") or data.get("report_quality_issues")
                or data.get("report_quality_status") in ("needs_confirmation", "failed")):
            continue
        note_id = data.get("saved_note_id") or data.get("_saved_note_id")
        if note_id is not None:
            if not isinstance(note_id, str) or not _ID.fullmatch(note_id):
                continue
            note = notes.get(note_id)
            if not note or note["domain"] != row["domain"] or _score(note["score"]) != _score(row["ces_percentile"]):
                continue
        event = _event("diagnosis", row["id"], user_id, note_id, row["domain"],
                       row["ces_percentile"], row["grade"], "analyze", row["created_at"])
        if event:
            events.append(event)
            if note_id:
                represented.add(note_id)
    for raw in storage.fetchall(
        "SELECT c.id,c.user_id,c.note_id,c.generate_ctx_json,r.status,r.complete_applied,r.refund_applied "
        "FROM chat_sessions c JOIN idempotency_requests r ON r.id=c.id AND r.user_id=c.user_id "
        "WHERE c.user_id=? AND r.operation='generate'", (user_id,)
    ):
        row = dict(raw)
        claimed_generation_notes.add(row["id"])
        if row["note_id"]:
            claimed_generation_notes.add(row["note_id"])
        task = _object(row["generate_ctx_json"]).get("task_continuation")
        if (row["status"] != "completed" or row["complete_applied"] != 1 or row["refund_applied"] != 0
                or not isinstance(task, dict) or task.get("status") != "completed" or task.get("operation") != "generate"):
            continue
        result = task.get("result")
        note = notes.get(row["note_id"])
        if (not note or not isinstance(result, dict) or result.get("saved_note_id") != note["id"]
                or result.get("quality_failed") or note["source"] != "generate"
                or _score(result.get("ces_percentile")) != _score(note["score"])):
            continue
        event = _event("generation", row["id"], user_id, note["id"], note["domain"],
                       note["score"], note["grade"], "generate", note["created_at"])
        if event:
            events.append(event)
            represented.add(note["id"])
    for note in notes.values():
        if note["id"] in represented or note["id"] in claimed_generation_notes:
            continue
        action = note["source"]
        if action == "chat":
            # A saved version is an optimization, never a guessed 0->score gain.
            parent = notes.get(note["parent_id"])
            if (not parent or parent["domain"] != note["domain"] or type(note["version"]) is not int
                    or type(parent["version"]) is not int or note["version"] <= parent["version"]):
                continue
            kind, action = "optimization", "chat_optimize"
        elif action in {"generate", "manual"}:
            kind = "saved_note"
        else:
            # A diagnosis note without its checked report does not prove a
            # completed diagnosis. Its existing growth record remains readable.
            continue
        event = _event(kind, note["id"], user_id, note["id"], note["domain"],
                       note["score"], note["grade"], action, note["created_at"])
        if event:
            events.append(event)
    ordered = sorted(events, key=lambda e: (e["source_recorded_at"], e["source_type"], e["source_id"]))
    # Multiple retained reports may refer to the same unchanged note version.
    # They provide more evidence for one saved scoring event, not new versions.
    unique, note_ids = [], set()
    for event in ordered:
        if event["note_id"] and event["note_id"] in note_ids:
            continue
        unique.append(event)
        if event["note_id"]:
            note_ids.add(event["note_id"])
    return unique


def _repair_id(event):
    return "recovered:" + event["source_type"] + ":" + event["source_id"]


def _same_event(row, event):
    if row["user_id"] != event["user_id"]:
        return False
    if row["id"] == _repair_id(event):
        return True
    # Never infer a link for old note-less diagnoses from score or time.
    return bool(event["note_id"] and row["note_id"] == event["note_id"]
                and row["action"] in _PREDICTION_ACTIONS and event["action"] in _PREDICTION_ACTIONS)


def _rows(storage, user_id):
    return [dict(r) for r in storage.fetchall(
        "SELECT id,user_id,note_id,score,grade,domain,action,recorded_at FROM growth_records WHERE user_id=?", (user_id,))]


def project_growth_history(storage, user_id, *, is_visible=None):
    """GET-safe merged history. A recoverable event is explicitly not persisted."""
    sources = load_source_events(storage, user_id, is_visible=is_visible)
    rows = _rows(storage, user_id)
    records, matched = [], set()
    for row in rows:
        if _score(row["score"]) is None or _clock(row["recorded_at"]) is None:
            continue
        source = next((event for event in sources if _same_event(row, event)), None)
        if source:
            matched.add((source["source_type"], source["source_id"]))
        recovered = bool(source and row["id"] == _repair_id(source))
        records.append({key: row[key] for key in ("id", "note_id", "score", "grade", "domain", "action", "recorded_at")}
                       | dict(source_type=source["source_type"] if source else "legacy",
                              source_id=source["source_id"] if source else None,
                              source_recorded_at=source["source_recorded_at"] if source else row["recorded_at"],
                              recovered_at=row["recorded_at"] if recovered else None,
                              record_origin="recovered" if recovered else "recorded", persisted=True,
                              score_kind="performance" if row["action"] in _PERFORMANCE_ACTIONS else "prediction"))
        if recovered:
            records[-1]["recorded_at"] = source["source_recorded_at"]
    for source in sources:
        if (source["source_type"], source["source_id"]) in matched:
            continue
        records.append({key: source[key] for key in ("note_id", "score", "grade", "domain", "action", "source_type", "source_id", "source_recorded_at")}
                       | dict(id=_repair_id(source), recorded_at=source["source_recorded_at"], recovered_at=None,
                              record_origin="recoverable", persisted=False, score_kind="prediction"))
    records.sort(key=lambda r: (_clock(r["recorded_at"]), r["id"]))
    scores = [r["score"] for r in records if r["score_kind"] == "prediction"]
    performance = [r for r in records if r["score_kind"] == "performance"]
    domains = {}
    for record in records:
        domains[record["domain"]] = domains.get(record["domain"], 0) + 1
    return dict(records=records, performance_records=performance,
                stats=dict(total_sessions=len(records), prediction_sessions=len(scores), performance_sessions=len(performance),
                best_score=max(scores) if scores else None,
                latest_score=scores[-1] if scores else None, avg_score=round(sum(scores)/len(scores), 1) if scores else None,
                domain_distribution=domains))


def _write_fence(storage, user_id):
    import content_retention
    content_retention.assert_user_writable_with_storage(storage, user_id)


def _achievements(storage, user_id, score, action, *, source_note_id=None, recorded_at=None):
    import memory
    return memory.check_and_record_achievements_with_storage(storage, user_id, score, action,
                source_note_id=source_note_id, recorded_at=recorded_at)


def repair_growth_history_with_storage(storage, user_id, *, repaired_at, is_visible=None):
    """Explicit idempotent repair inside the caller's write transaction.

The original source time remains in its retained source; recorded_at records the
actual repair. Deterministic text IDs retain the exact source type/identity. No
existing row is deleted/relabelled, and an unbound old event is never guessed.
    """
    repaired_at = _clock(repaired_at)
    if repaired_at is None:
        raise ValueError("growth_repair_time_invalid")
    _write_fence(storage, user_id)
    sources, rows = load_source_events(storage, user_id, is_visible=is_visible), _rows(storage, user_id)
    repaired, achieved = [], []
    for source in sources:
        if _clock(source["source_recorded_at"]) > repaired_at:
            raise ValueError("growth_repair_before_source")
        found = next((row for row in rows if _same_event(row, source)), None)
        if found is not None and (found["domain"] != source["domain"] or _score(found["score"]) != source["score"]):
            raise ValueError("growth_existing_source_conflict")
        if found is None:
            identity = _repair_id(source)
            storage.execute("INSERT INTO growth_records(id,user_id,note_id,domain,score,grade,action,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                (identity, user_id, source["note_id"], source["domain"], source["score"], source["grade"], source["action"], repaired_at))
            rows.append(dict(source, id=identity, recorded_at=repaired_at))
            repaired.append(dict(source_type=source["source_type"], source_id=source["source_id"], record_id=identity,
                                 source_recorded_at=source["source_recorded_at"], repaired_at=repaired_at))
        # Also repair a missed achievement after an existing canonical growth
        # insert; the memory helper deduplicates under the same user fence.
        achieved.extend(_achievements(storage, user_id, source["score"], source["action"],
                        source_note_id=source["note_id"], recorded_at=repaired_at))
    return dict(repaired=repaired, inserted_count=len(repaired), achievements=achieved, repaired_at=repaired_at)


def record_saved_note_with_storage(storage, *, user_id, note_id, domain, score, grade, action,
                                   recorded_at=None, record_id=None):
    """Completion hook; caller owns the canonical save transaction and source.

Existing note-bound legacy rows suppress duplicate completion callbacks. A
note-less diagnosis needs its caller's identity (or gets one new event UUID).
    """
    score = _score(score)
    if score is None or action not in _PREDICTION_ACTIONS:
        raise ValueError("growth_score_or_action_invalid")
    recorded_at = _clock(recorded_at or datetime.now(timezone.utc).isoformat())
    if recorded_at is None:
        raise ValueError("growth_time_invalid")
    _write_fence(storage, user_id)
    if note_id is not None:
        note = storage.fetchone("SELECT id,user_id,score,domain FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        if not note or _score(note["score"]) != score or note["domain"] != domain:
            raise ValueError("growth_note_binding_invalid")
        existing = [r for r in _rows(storage, user_id) if r["note_id"] == note_id and r["action"] in _PREDICTION_ACTIONS]
    else:
        existing = [r for r in _rows(storage, user_id) if record_id is not None and r["id"] == record_id]
    if any(_score(r["score"]) != score or r["domain"] != domain for r in existing):
        raise ValueError("growth_existing_source_conflict")
    if not existing:
        identity = record_id or ("saved:" + note_id if note_id else str(uuid.uuid4()))
        storage.execute("INSERT INTO growth_records(id,user_id,note_id,domain,score,grade,action,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                        (identity, user_id, note_id, domain, score, grade, action, recorded_at))
    return _achievements(storage, user_id, score, action, source_note_id=note_id, recorded_at=recorded_at)
