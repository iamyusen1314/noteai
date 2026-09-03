"""
NoteAI Pro Prompt 管理器
- 从主数据库加载 prompt（首次启动由 prompts.json/defaults 初始化）
- 支持热加载（无需重启 api.py）
- 版本历史由 admin_server.py 写入共享数据库
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import db
import prompt_baselines

_PROMPTS_FILE = Path(__file__).parent / "prompts.json"
_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 10  # 秒，10s 内不重复访问数据库
_BASELINE_MARKER_KEY = "managed_prompt_baseline"
_BASELINE_ADVISORY_LOCK = "noteai_managed_prompt_baseline_v04"


class PromptBaselineRollbackBlocked(RuntimeError):
    pass


def _file_prompts() -> dict:
    if not _PROMPTS_FILE.exists():
        return {}
    try:
        data = json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
        return data.get("prompts", {})
    except Exception:
        return {}


def _load() -> dict:
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL and _cache:
        return _cache
    rows = db.fetchall(
        "SELECT key,label,module,content,version,updated_at FROM managed_prompts"
    )
    _cache = {
        row["key"]: {
            "key": row["key"],
            "label": row["label"],
            "module": row["module"],
            "content": row["content"],
            "version": row["version"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    }
    _cache_ts = now
    return _cache


def get(key: str, fallback: str = "") -> str:
    """获取 prompt。优先共享数据库，否则返回代码内 fallback。"""
    prompts = _load()
    p = prompts.get(key)
    if p and p.get("content"):
        return p["content"]
    return fallback


def reload() -> int:
    """强制刷新缓存，返回加载的 prompt 数量。"""
    global _cache_ts
    _cache_ts = 0
    return len(_load())


def init_default_prompts(defaults: dict[str, dict]) -> None:
    """把文件/代码默认值写入空缺键，不覆盖后台已经编辑的内容。"""
    file_defaults = _file_prompts()
    for key, meta in defaults.items():
        if db.fetchone("SELECT key FROM managed_prompts WHERE key=?", (key,)):
            continue
        source = file_defaults.get(key, {})
        db.execute(
            "INSERT INTO managed_prompts(key,label,module,content,version,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                key,
                source.get("label") or meta.get("label", key),
                source.get("module") or meta.get("module", ""),
                source.get("content") or meta.get("content", ""),
                int(source.get("version") or 1),
                source.get("updated_at") or "2026-06-17T00:00:00+00:00",
            ),
        )
    global _cache_ts
    _cache_ts = 0


def _content_sha256(content: str) -> str:
    return prompt_baselines.content_sha256(content)


def _classify_prompt_row(key: str, row: dict | None, current: dict) -> str:
    if row is None:
        return "missing"
    if _content_sha256(row.get("content") or "") == _content_sha256(current["content"]):
        return "already_current"
    if prompt_baselines.is_accepted_legacy(key, int(row.get("version") or 0), row.get("content") or ""):
        return "eligible_update"
    return "skipped_custom"


def _summary_template(*, dry_run: bool) -> dict[str, int | str | bool]:
    return {
        "baseline_id": prompt_baselines.BASELINE_ID,
        "dry_run": dry_run,
        "missing": 0,
        "eligible_update": 0,
        "already_current": 0,
        "skipped_custom": 0,
        "inserted": 0,
        "updated": 0,
    }


def audit_versioned_baseline() -> dict:
    current = prompt_baselines.load_current_baseline()
    rows = {
        row["key"]: dict(row)
        for row in db.fetchall(
            "SELECT key,label,module,content,version,updated_at FROM managed_prompts"
        )
    }
    result = _summary_template(dry_run=True)
    for key in prompt_baselines.PROMPT_KEYS:
        state = _classify_prompt_row(key, rows.get(key), current[key])
        result[state] += 1
    return result


def _locked_row(transaction: db.Transaction, key: str) -> dict | None:
    suffix = " FOR UPDATE" if transaction.postgres else ""
    row = transaction.fetchone(
        "SELECT key,label,module,content,version,updated_at "
        f"FROM managed_prompts WHERE key=?{suffix}",
        (key,),
    )
    return dict(row) if row else None


def _acquire_baseline_advisory_lock(transaction: db.Transaction) -> None:
    """Serialize only managed-Prompt baseline apply/rollback on PostgreSQL."""
    if not transaction.postgres:
        return
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtext(?))",
        (_BASELINE_ADVISORY_LOCK,),
    )


def _write_baseline_marker(transaction: db.Transaction, marker: dict, now: str) -> None:
    encoded = json.dumps(marker, ensure_ascii=False, separators=(",", ":"))
    existing = transaction.fetchone("SELECT key FROM system_settings WHERE key=?", (_BASELINE_MARKER_KEY,))
    if existing:
        transaction.execute(
            "UPDATE system_settings SET value_json=?,is_secret=0,updated_at=? WHERE key=?",
            (encoded, now, _BASELINE_MARKER_KEY),
        )
    else:
        transaction.execute(
            "INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,0,?)",
            (_BASELINE_MARKER_KEY, encoded, now),
        )


def apply_versioned_baseline(*, dry_run: bool = False) -> dict:
    """Safely insert or upgrade the 12 managed Prompt baselines.

    Existing rows are upgraded only when both their version and exact UTF-8
    SHA256 match a source-controlled legacy seed.
    """
    if dry_run:
        return audit_versioned_baseline()

    current = prompt_baselines.load_current_baseline()
    result = _summary_template(dry_run=False)
    now = datetime.now(timezone.utc).isoformat()
    upgraded: list[dict] = []
    inserted_keys: list[str] = []
    with db.transaction(write=True) as transaction:
        _acquire_baseline_advisory_lock(transaction)
        for key in prompt_baselines.PROMPT_KEYS:
            baseline = current[key]
            row = _locked_row(transaction, key)
            state = _classify_prompt_row(key, row, baseline)
            result[state] += 1
            if state == "missing":
                transaction.execute(
                    "INSERT INTO managed_prompts(key,label,module,content,version,updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        key,
                        baseline.get("label") or key,
                        baseline.get("module") or "",
                        baseline["content"],
                        int(baseline.get("version") or 1),
                        now,
                    ),
                )
                inserted_keys.append(key)
                result["inserted"] += 1
                continue
            if state != "eligible_update":
                continue
            old_version = int(row.get("version") or 0)
            new_version = old_version + 1
            transaction.execute(
                "INSERT INTO prompt_history(prompt_key,version,content,saved_at) VALUES(?,?,?,?)",
                (key, old_version, row["content"], row.get("updated_at") or now),
            )
            transaction.execute(
                "UPDATE managed_prompts SET label=?,module=?,content=?,version=?,updated_at=? WHERE key=?",
                (
                    baseline.get("label") or row.get("label") or key,
                    baseline.get("module") or row.get("module") or "",
                    baseline["content"],
                    new_version,
                    now,
                    key,
                ),
            )
            upgraded.append({
                "key": key,
                "from_version": old_version,
                "to_version": new_version,
                "from_label": row.get("label") or key,
                "from_module": row.get("module") or "",
            })
            result["updated"] += 1

        if upgraded or inserted_keys:
            _write_baseline_marker(transaction, {
                "baseline_id": prompt_baselines.BASELINE_ID,
                "status": "applied",
                "applied_at": now,
                "upgraded": upgraded,
                "inserted_keys": inserted_keys,
            }, now)

    global _cache_ts
    _cache_ts = 0
    return result


def rollback_versioned_baseline() -> dict:
    """Restore upgraded rows and remove rows inserted by this baseline.

    Any later edit blocks the entire rollback before a row is changed.
    """
    current = prompt_baselines.load_current_baseline()
    now = datetime.now(timezone.utc).isoformat()
    with db.transaction(write=True) as transaction:
        _acquire_baseline_advisory_lock(transaction)
        marker_row = transaction.fetchone(
            "SELECT value_json FROM system_settings WHERE key=?",
            (_BASELINE_MARKER_KEY,),
        )
        if not marker_row:
            raise PromptBaselineRollbackBlocked("prompt baseline marker is missing")
        try:
            marker = json.loads(marker_row["value_json"])
        except (TypeError, ValueError):
            raise PromptBaselineRollbackBlocked("prompt baseline marker is invalid") from None
        if not isinstance(marker, dict):
            raise PromptBaselineRollbackBlocked("prompt baseline marker is invalid")
        if marker.get("baseline_id") != prompt_baselines.BASELINE_ID or marker.get("status") != "applied":
            raise PromptBaselineRollbackBlocked("prompt baseline marker does not permit rollback")

        upgraded_marker = marker.get("upgraded")
        if not isinstance(upgraded_marker, list):
            raise PromptBaselineRollbackBlocked("prompt upgraded marker is invalid")
        validated_upgrades: list[dict] = []
        upgraded_keys: set[str] = set()
        for item in upgraded_marker:
            if not isinstance(item, dict):
                raise PromptBaselineRollbackBlocked("prompt upgraded marker is invalid")
            key = item.get("key")
            from_version = item.get("from_version")
            to_version = item.get("to_version")
            if (
                not isinstance(key, str)
                or not key
                or key not in current
                or key in upgraded_keys
                or not isinstance(from_version, int)
                or isinstance(from_version, bool)
                or from_version < 1
                or not isinstance(to_version, int)
                or isinstance(to_version, bool)
                or to_version != from_version + 1
                or not isinstance(item.get("from_label"), str)
                or not isinstance(item.get("from_module"), str)
            ):
                raise PromptBaselineRollbackBlocked("prompt upgraded marker is invalid")
            upgraded_keys.add(key)
            validated_upgrades.append(item)

        inserted_keys = marker.get("inserted_keys")
        if (
            not isinstance(inserted_keys, list)
            or any(not isinstance(key, str) for key in inserted_keys)
            or len(inserted_keys) != len(set(inserted_keys))
            or any(not key or key not in current for key in inserted_keys)
            or upgraded_keys.intersection(inserted_keys)
        ):
            raise PromptBaselineRollbackBlocked("prompt inserted marker is invalid")

        restore_rows: list[tuple[dict, dict]] = []
        for item in validated_upgrades:
            key = item["key"]
            row = _locked_row(transaction, key)
            if not row or int(row.get("version") or 0) != int(item.get("to_version") or -1):
                raise PromptBaselineRollbackBlocked("prompt changed after baseline apply")
            baseline = current[key]
            if (
                _content_sha256(row.get("content") or "") != _content_sha256(baseline["content"])
                or row.get("label") != baseline.get("label")
                or row.get("module") != baseline.get("module")
            ):
                raise PromptBaselineRollbackBlocked("prompt changed after baseline apply")
            history = transaction.fetchone(
                "SELECT content,saved_at FROM prompt_history "
                "WHERE prompt_key=? AND version=? ORDER BY id DESC LIMIT 1",
                (key, int(item.get("from_version") or 0)),
            )
            if not history:
                raise PromptBaselineRollbackBlocked("prompt rollback history is missing")
            restore_rows.append((item, dict(history)))

        remove_keys: list[str] = []
        inserted_set = set(inserted_keys)
        for key in prompt_baselines.PROMPT_KEYS:
            if key not in inserted_set:
                continue
            row = _locked_row(transaction, key)
            baseline = current[key]
            if not row or int(row.get("version") or 0) != int(baseline.get("version") or 1):
                raise PromptBaselineRollbackBlocked("inserted prompt changed after baseline apply")
            if (
                _content_sha256(row.get("content") or "") != _content_sha256(baseline["content"])
                or row.get("label") != baseline.get("label")
                or row.get("module") != baseline.get("module")
            ):
                raise PromptBaselineRollbackBlocked("inserted prompt changed after baseline apply")
            remove_keys.append(key)

        for item, history in restore_rows:
            transaction.execute(
                "UPDATE managed_prompts SET label=?,module=?,content=?,version=?,updated_at=? WHERE key=?",
                (
                    item.get("from_label") or item["key"],
                    item.get("from_module") or "",
                    history["content"],
                    int(item["from_version"]),
                    history.get("saved_at") or now,
                    item["key"],
                ),
            )
        for key in remove_keys:
            transaction.execute("DELETE FROM managed_prompts WHERE key=?", (key,))
        marker["status"] = "rolled_back"
        marker["rolled_back_at"] = now
        marker["restored_count"] = len(restore_rows)
        marker["removed_count"] = len(remove_keys)
        _write_baseline_marker(transaction, marker, now)

    global _cache_ts
    _cache_ts = 0
    return {
        "baseline_id": prompt_baselines.BASELINE_ID,
        "restored": len(restore_rows),
        "removed": len(remove_keys),
    }
