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
import prompt_manager  # noqa: E402


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if not db.using_postgres():
        print("DATABASE_URL must use PostgreSQL", file=sys.stderr)
        return 2
    applied = db.apply_postgres_migrations()
    prompt_audit = prompt_manager.audit_versioned_baseline()
    print(
        "prompt_baseline_audit=ok "
        f"missing={prompt_audit['missing']} eligible={prompt_audit['eligible_update']} "
        f"current={prompt_audit['already_current']} skipped={prompt_audit['skipped_custom']}"
    )
    prompt_result = prompt_manager.apply_versioned_baseline()
    health = db.database_health()
    if not health.get("ok"):
        print("PostgreSQL health check failed", file=sys.stderr)
        return 1
    print(f"database_backend={health['backend']} migrations_applied={len(applied)}")
    for version in applied:
        print(f"applied={version}")
    print(
        "prompt_baseline_status=ok "
        f"inserted={prompt_result['inserted']} updated={prompt_result['updated']} "
        f"current={prompt_result['already_current']} skipped={prompt_result['skipped_custom']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
