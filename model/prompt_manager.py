"""
NoteAI Pro Prompt 管理器
- 从 prompts.json 加载 prompt（优先级 > 代码内 hardcode）
- 支持热加载（无需重启 api.py）
- 版本历史由 admin_server.py 维护
"""
import json
import time
from pathlib import Path
from typing import Optional

_PROMPTS_FILE = Path(__file__).parent / "prompts.json"
_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 10  # 秒，10s 内不重复读文件


def _load() -> dict:
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL and _cache:
        return _cache
    if _PROMPTS_FILE.exists():
        try:
            data = json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
            _cache = data.get("prompts", {})
            _cache_ts = now
            return _cache
        except Exception:
            pass
    return {}


def get(key: str, fallback: str = "") -> str:
    """获取 prompt。优先 prompts.json，否则返回 fallback（代码内 hardcode）。"""
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
    """初始化：如果 prompts.json 不存在对应 key，写入默认值（不覆盖已有自定义）。"""
    if not _PROMPTS_FILE.exists():
        data = {"prompts": {}, "history": {}}
    else:
        try:
            data = json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {"prompts": {}, "history": {}}

    changed = False
    for key, meta in defaults.items():
        if key not in data["prompts"]:
            data["prompts"][key] = {
                "key":        key,
                "label":      meta.get("label", key),
                "module":     meta.get("module", ""),
                "content":    meta.get("content", ""),
                "version":    1,
                "updated_at": "2026-06-17T00:00:00+00:00",
            }
            changed = True

    if changed:
        _PROMPTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    global _cache_ts
    _cache_ts = 0  # 让下次 get 强制重新读取
