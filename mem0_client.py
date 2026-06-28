"""
NoteAI Pro — mem0 memory client.
Maps to the user_memory system described in PRD section 4.5 / 6.3.
Completely separate from baseline_notes (Model A training data).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".mem0"))
from config import get_memory  # noqa: E402

_memory = None


def memory():
    global _memory
    if _memory is None:
        _memory = get_memory()
    return _memory


# ── User Memory API ───────────────────────────────────────────────

def remember_diagnosis(user_id: str, messages: list[dict]) -> dict:
    """Store a diagnosis session in user memory."""
    return memory().add(messages, user_id=user_id, metadata={"source": "diagnosis"})


def remember_style_preference(user_id: str, preference: str) -> dict:
    """Store a user style preference (e.g. 'prefers minimalist covers')."""
    msg = [{"role": "user", "content": preference}]
    return memory().add(msg, user_id=user_id, metadata={"source": "style_pref"})


def recall(user_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Retrieve relevant memories for a user."""
    results = memory().search(query, filters={"user_id": user_id}, limit=top_k)
    return results.get("results", [])


def get_all(user_id: str) -> list[dict]:
    """Return full memory history for a user (Growth Profile page)."""
    results = memory().get_all(filters={"user_id": user_id})
    return results.get("results", [])


def delete_user(user_id: str) -> None:
    """GDPR: delete all memories for a user."""
    memory().delete_all(user_id=user_id)
