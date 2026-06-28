"""
NoteAI 用户记忆系统 — 纯 SQLite，替代外部 mem0 服务。

记忆分四类：
  style       写作风格偏好（如"接地气"、"少表情"）
  preference  内容偏好（如"短正文"、"多步骤"）
  achievement 成就里程碑（如"首次突破70分"）
  context     对话上下文摘要（最近3次生成的关键决策）

注入策略：按 importance 降序，取前 N 条拼成 system prompt 片段。
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import db

_MAX_CONTEXT_MEMORIES = 3   # 最多注入几条上下文记忆
_MAX_STYLE_MEMORIES   = 5   # 最多注入几条风格/偏好记忆
_DECAY_ON_ACCESS      = 0.98  # 每次被注入时轻微衰减（让旧记忆逐渐淡出）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# 写入
# ─────────────────────────────────────────────────────────────

def add_memory(
    user_id: str,
    memory_type: str,
    content: str,
    importance: float = 0.6,
) -> str:
    """添加一条记忆，返回 id。"""
    mid = str(uuid.uuid4())
    now = _now()
    db.execute(
        "INSERT INTO user_memories(id,user_id,memory_type,content,importance,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (mid, user_id, memory_type, content, importance, now, now),
    )
    return mid


def upsert_style(user_id: str, key: str, value: str, importance: float = 0.75) -> None:
    """更新或新增一条风格偏好（以 key 去重）。"""
    content = f"{key}:{value}"
    row = db.fetchone(
        "SELECT id FROM user_memories WHERE user_id=? AND memory_type='style' AND content LIKE ?",
        (user_id, f"{key}:%"),
    )
    now = _now()
    if row:
        db.execute(
            "UPDATE user_memories SET content=?,importance=?,updated_at=? WHERE id=?",
            (content, min(importance + 0.05, 0.95), now, row["id"]),
        )
    else:
        add_memory(user_id, "style", content, importance)


def record_achievement(user_id: str, text: str) -> None:
    """记录一次成就（不去重，每次都写）。"""
    add_memory(user_id, "achievement", text, importance=0.9)


def add_context(user_id: str, summary: str) -> None:
    """追加一条上下文记忆，并自动清理超出限制的旧记录。"""
    add_memory(user_id, "context", summary, importance=0.5)
    # 保留最新 _MAX_CONTEXT_MEMORIES*2 条，删除多余旧条
    rows = db.fetchall(
        "SELECT id FROM user_memories WHERE user_id=? AND memory_type='context'"
        " ORDER BY created_at DESC",
        (user_id,),
    )
    if len(rows) > _MAX_CONTEXT_MEMORIES * 2:
        old_ids = [r["id"] for r in rows[_MAX_CONTEXT_MEMORIES * 2 :]]
        for oid in old_ids:
            db.execute("DELETE FROM user_memories WHERE id=?", (oid,))


# ─────────────────────────────────────────────────────────────
# 读取 & 注入
# ─────────────────────────────────────────────────────────────

def recall(user_id: str, memory_type: Optional[str] = None, limit: int = 10) -> list[dict]:
    """查询用户记忆，按 importance 降序。"""
    if memory_type:
        rows = db.fetchall(
            "SELECT * FROM user_memories WHERE user_id=? AND memory_type=?"
            " ORDER BY importance DESC LIMIT ?",
            (user_id, memory_type, limit),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM user_memories WHERE user_id=?"
            " ORDER BY importance DESC LIMIT ?",
            (user_id, limit),
        )
    return [dict(r) for r in rows]


def build_memory_prompt(user_id: str) -> str:
    """
    构建注入到 system prompt 的记忆片段。
    返回空字符串表示无记忆（匿名用户）。
    """
    if not user_id:
        return ""

    style_rows   = db.fetchall(
        "SELECT content FROM user_memories WHERE user_id=? AND memory_type IN ('style','preference')"
        " ORDER BY importance DESC LIMIT ?",
        (user_id, _MAX_STYLE_MEMORIES),
    )
    context_rows = db.fetchall(
        "SELECT content FROM user_memories WHERE user_id=? AND memory_type='context'"
        " ORDER BY created_at DESC LIMIT ?",
        (user_id, _MAX_CONTEXT_MEMORIES),
    )
    achieve_rows = db.fetchall(
        "SELECT content FROM user_memories WHERE user_id=? AND memory_type='achievement'"
        " ORDER BY created_at DESC LIMIT 2",
        (user_id,),
    )

    # 访问衰减（更新 importance）
    all_ids = [r["id"] for rows in [
        db.fetchall("SELECT id FROM user_memories WHERE user_id=? AND memory_type IN ('style','preference') ORDER BY importance DESC LIMIT ?", (user_id, _MAX_STYLE_MEMORIES)),
        db.fetchall("SELECT id FROM user_memories WHERE user_id=? AND memory_type='context' ORDER BY created_at DESC LIMIT ?", (user_id, _MAX_CONTEXT_MEMORIES)),
    ] for r in rows]
    if all_ids:
        now = _now()
        for mid in all_ids:
            db.execute(
                "UPDATE user_memories SET importance=importance*?,access_count=access_count+1,updated_at=? WHERE id=?",
                (_DECAY_ON_ACCESS, now, mid),
            )

    parts = []
    if style_rows:
        prefs = "; ".join(r["content"] for r in style_rows)
        parts.append(f"【用户写作偏好】{prefs}")
    if context_rows:
        ctx = "; ".join(r["content"] for r in context_rows)
        parts.append(f"【近期优化记录】{ctx}")
    if achieve_rows:
        ach = "; ".join(r["content"] for r in achieve_rows)
        parts.append(f"【成长里程碑】{ach}")

    return "\n".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────
# 从 user_learn 表同步偏好到 user_memories（双写桥接）
# ─────────────────────────────────────────────────────────────

def sync_from_user_learn(user_id: str, prefs: dict) -> None:
    """将 /chat 学习信号写入的 user_learn 偏好同步到 user_memories。"""
    for key, value in prefs.items():
        upsert_style(user_id, key, value)


# ─────────────────────────────────────────────────────────────
# 成就检测
# ─────────────────────────────────────────────────────────────

def check_and_record_achievements(user_id: str, score: float, action: str) -> list[str]:
    """检测里程碑，有新成就则写入并返回成就文本列表。"""
    if not user_id or score is None:
        return []
    achieved = []
    rows = db.fetchall(
        "SELECT content FROM user_memories WHERE user_id=? AND memory_type='achievement'",
        (user_id,),
    )
    existing = {r["content"] for r in rows}

    milestones = [
        (50, "首次评分突破50分"),
        (60, "首次评分突破60分"),
        (65, "首次评分突破65分"),
        (70, "首次评分突破70分 🎉"),
        (75, "首次评分突破75分 🏆"),
        (80, "首次评分突破80分 🌟"),
    ]
    for threshold, text in milestones:
        if score >= threshold and text not in existing:
            record_achievement(user_id, text)
            achieved.append(text)
    return achieved
