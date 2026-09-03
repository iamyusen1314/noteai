"""Shared runtime settings backed by the primary database."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import db


class SecretStorageUnavailable(RuntimeError):
    """Raised when a caller tries to persist a secret in the settings table."""


_SECRET_ENV_KEYS = {
    "xhs_cookies": "NOTEAI_XHS_COOKIES_JSON",
}


def get_json(key: str, default: Any = None) -> Any:
    secret_env = _SECRET_ENV_KEYS.get(key)
    if secret_env:
        if not os.environ.get(secret_env):
            return default
        try:
            return json.loads(os.environ[secret_env])
        except (TypeError, ValueError):
            return default
    row = db.fetchone(
        "SELECT value_json,is_secret FROM system_settings WHERE key=?",
        (key,),
    )
    if not row:
        return default
    # Historical rows may contain plaintext secrets. They are deliberately
    # unreadable through the runtime API and should be removed by a separately
    # approved production cleanup.
    if bool(row["is_secret"]):
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, ValueError):
        return default


def set_json(key: str, value: Any, *, is_secret: bool = False) -> None:
    if is_secret or key in _SECRET_ENV_KEYS:
        raise SecretStorageUnavailable(
            "敏感配置禁止写入数据库；请通过受管 Secret 注入运行环境"
        )
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
