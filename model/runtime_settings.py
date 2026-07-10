"""Shared runtime settings backed by the primary database."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import db


def get_json(key: str, default: Any = None) -> Any:
    row = db.fetchone("SELECT value_json FROM system_settings WHERE key=?", (key,))
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, ValueError):
        return default


def set_json(key: str, value: Any, *, is_secret: bool = False) -> None:
    encoded = json.dumps(value, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    existing = db.fetchone("SELECT key FROM system_settings WHERE key=?", (key,))
    if existing:
        db.execute(
            "UPDATE system_settings SET value_json=?, is_secret=?, updated_at=? WHERE key=?",
            (encoded, int(is_secret), now, key),
        )
        return
    db.execute(
        "INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,?,?)",
        (key, encoded, int(is_secret), now),
    )


def delete(key: str) -> None:
    db.execute("DELETE FROM system_settings WHERE key=?", (key,))
