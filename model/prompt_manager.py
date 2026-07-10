"""
NoteAI Pro Prompt 管理器
- 从主数据库加载 prompt（首次启动由 prompts.json/defaults 初始化）
- 支持热加载（无需重启 api.py）
- 版本历史由 admin_server.py 写入共享数据库
"""
import json
import time
from pathlib import Path
from typing import Optional

import db

_PROMPTS_FILE = Path(__file__).parent / "prompts.json"
_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 10  # 秒，10s 内不重复访问数据库


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
