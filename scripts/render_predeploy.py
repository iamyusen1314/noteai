#!/usr/bin/env python3
"""Apply NoteAI's versioned PostgreSQL migrations before a Render deploy."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
sys.path.insert(0, str(MODEL_DIR))

import db  # noqa: E402


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if not db.using_postgres():
        print("DATABASE_URL must use PostgreSQL", file=sys.stderr)
        return 2
    applied = db.apply_postgres_migrations()
    health = db.database_health()
    if not health.get("ok"):
        print("PostgreSQL health check failed", file=sys.stderr)
        return 1
    print(f"database_backend={health['backend']} migrations_applied={len(applied)}")
    for version in applied:
        print(f"applied={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
