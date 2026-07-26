"""NoteAI primary data access for local SQLite and cloud PostgreSQL."""
import hashlib
import sqlite3
import os
import re
import time
from contextlib import closing, contextmanager
from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
    timezone as _timezone,
)
from pathlib import Path
from typing import Any

_DB_PATH = Path(
    os.environ.get("NOTEAI_SQLITE_PATH")
    or (Path(__file__).parent / "data" / "noteai.db")
)
_POSTGRES_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "postgres"
_POSTGRES_LEGACY_MIGRATION_SHA256 = {
    "0001_initial.sql": (
        "8ea5d32bc5c1a3e84452d93722324b9a9b4bb2e156c69b4a9656efa13ed51718"
    ),
    "0002_shared_runtime_state.sql": (
        "d3a939479990cfe080fce71ebd122e19e633874bd2cd6883b5b03507eadefcb7"
    ),
    "0003_market_timing.sql": (
        "772636cab88c2abf169a5b1a3fd5419ba1e3b12bbae92e211e296e89b1850192"
    ),
    "0004_xhs_freshness.sql": (
        "1c817056eea3df9e0e1dd6ba6aceaf0c9a172b3cbba92ba3aeb621adb857a2a1"
    ),
    "0005_idempotency_requests.sql": (
        "3a02a45bf0211580c5db97fc80ab9fb8eedab94a9cf981c59f3de231789981e6"
    ),
    "0006_model_usage_records.sql": (
        "392eb82adca68493566f6469ce6ce4f1fba0cfc9ab76757deb4e1404c45cb735"
    ),
    "0007_ai_operations.sql": (
        "477d4ea776d701c4b359b36eb254c68263131f74dedeb766ff46081bff619037"
    ),
    "0008_ai_operation_admissions.sql": (
        "3bdd896ce06f7a5ae8deeba01145d9556775c45a71cd83576240d24a01bc05fe"
    ),
}
_RETENTION_SOURCE_CLOCK_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"[T ](?:[01]\d|2[0-3]):[0-5]\d"
    r"(?::[0-5]\d(?:\.\d{1,6})?)?"
    r"(?:Z|[+-](?:(?:0\d|1[0-3])(?::?[0-5]\d)?|14(?::?00)?))?$"
)
_RETENTION_DEADLINE_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"[T ](?:[01][0-9]|2[0-3]):[0-5][0-9]"
    r"(?::[0-5][0-9](?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-](?:(?:0[0-9]|1[0-3])(?::?[0-5][0-9])?|14(?::?00)?))$"
)


def _parse_retention_source_clock(value: Any) -> _datetime | None:
    """Return one precise UTC clock; legacy timezone-naive clocks mean UTC."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or not _RETENTION_SOURCE_CLOCK_RE.fullmatch(normalized):
        return None
    try:
        parsed = _datetime.fromisoformat(
            normalized[:-1] + "+00:00"
            if normalized.endswith("Z")
            else normalized
        )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone.utc)
    if parsed.utcoffset() is None:
        return None
    if abs(parsed.utcoffset()) > _timedelta(hours=14):
        return None
    return parsed.astimezone(_timezone.utc)


def _valid_retention_source_clock(value: Any) -> bool:
    """Accept only real clocks with deterministic UTC semantics."""
    return _parse_retention_source_clock(value) is not None


def _parse_retention_deadline_clock(value: Any) -> _datetime | None:
    """Parse one canonical, explicitly zoned retention deadline."""
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _RETENTION_DEADLINE_CLOCK_RE.fullmatch(value)
    ):
        return None
    try:
        parsed = _datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    if abs(parsed.utcoffset()) > _timedelta(hours=14):
        return None
    return parsed.astimezone(_timezone.utc)


def _sqlite_retention_clock_valid(value: Any) -> int:
    return int(_parse_retention_deadline_clock(value) is not None)


def _sqlite_retention_clock_lte(left: Any, right: Any) -> int:
    left_clock = _parse_retention_deadline_clock(left)
    right_clock = _parse_retention_deadline_clock(right)
    return int(
        left_clock is not None
        and right_clock is not None
        and left_clock <= right_clock
    )


def _sqlite_tracking_clock_valid(value: Any) -> int:
    return int(_parse_retention_deadline_clock(value) is not None)


def _sqlite_tracking_clock_lte(left: Any, right: Any) -> int:
    left_clock = _parse_retention_deadline_clock(left)
    right_clock = _parse_retention_deadline_clock(right)
    return int(
        left_clock is not None
        and right_clock is not None
        and left_clock <= right_clock
    )


def _retention_now() -> _datetime:
    return _datetime.now(_timezone.utc)


def _sqlite_retention_clock_not_future(value: Any) -> int:
    clock = _parse_retention_deadline_clock(value)
    return int(clock is not None and clock <= _retention_now())


def _valid_content_retention_row(row: Any) -> bool:
    retention_class = row["retention_class"]
    active_until = row["active_until"]
    recovery_until = row["recovery_until"]
    deleted_at = row["deleted_at"]
    purge_after = row["purge_after"]
    purged_at = row["purged_at"]
    deleted_clock = _parse_retention_deadline_clock(deleted_at)
    purge_clock = _parse_retention_deadline_clock(purge_after)
    purged_clock = _parse_retention_deadline_clock(purged_at)
    if retention_class == "paid_indefinite":
        if active_until is not None or recovery_until is not None:
            return False
        if deleted_at is None:
            return purge_after is None and purged_at is None
        return (
            deleted_clock is not None
            and purge_clock is not None
            and deleted_clock <= purge_clock
            and (
                purged_at is None
                or (
                    purged_clock is not None
                    and purge_clock <= purged_clock
                    and purged_clock <= _retention_now()
                )
            )
        )
    if retention_class != "free_7d":
        return False
    active_clock = _parse_retention_deadline_clock(active_until)
    recovery_clock = _parse_retention_deadline_clock(recovery_until)
    return (
        active_clock is not None
        and recovery_clock is not None
        and purge_clock is not None
        and active_clock <= recovery_clock <= purge_clock
        and (
            deleted_at is None
            or (
                deleted_clock is not None
                and deleted_clock <= purge_clock
            )
        )
        and (
            purged_at is None
            or (
                purged_clock is not None
                and purge_clock <= purged_clock
                and purged_clock <= _retention_now()
            )
        )
    )


class CompatRow(dict):
    """Mapping row with sqlite.Row-compatible integer indexing."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _compat_row_factory(cursor):
    columns = [column.name for column in (cursor.description or ())]

    def make_row(values):
        return CompatRow(zip(columns, values))

    return make_row


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def using_postgres() -> bool:
    return _database_url().lower().startswith(("postgres://", "postgresql://"))


def _get_sqlite_conn(*, timeout_seconds: float | None = None) -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connect_kwargs: dict[str, Any] = {"check_same_thread": False}
    if timeout_seconds is not None:
        connect_kwargs["timeout"] = max(0.1, float(timeout_seconds))
    conn = sqlite3.connect(str(_DB_PATH), **connect_kwargs)
    conn.row_factory = sqlite3.Row
    conn.create_function(
        "noteai_retention_clock_valid",
        1,
        _sqlite_retention_clock_valid,
        deterministic=True,
    )
    conn.create_function(
        "noteai_retention_clock_lte",
        2,
        _sqlite_retention_clock_lte,
        deterministic=True,
    )
    conn.create_function(
        "noteai_retention_clock_not_future",
        1,
        _sqlite_retention_clock_not_future,
    )
    conn.create_function(
        "noteai_tracking_clock_valid",
        1,
        _sqlite_tracking_clock_valid,
        deterministic=True,
    )
    conn.create_function(
        "noteai_tracking_clock_lte",
        2,
        _sqlite_tracking_clock_lte,
        deterministic=True,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    busy_timeout_ms = (
        10000
        if timeout_seconds is None
        else max(100, int(float(timeout_seconds) * 1000))
    )
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    return conn


def _get_postgres_conn(
    *,
    connect_timeout_seconds: int | None = None,
    statement_timeout_ms: int | None = None,
):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL requires psycopg[binary]") from exc
    connect_kwargs: dict[str, Any] = {
        "row_factory": _compat_row_factory,
        "options": "-c timezone=UTC",
    }
    if connect_timeout_seconds is not None:
        connect_kwargs["connect_timeout"] = max(1, int(connect_timeout_seconds))
    if statement_timeout_ms is not None:
        timeout_ms = max(100, int(statement_timeout_ms))
        connect_kwargs["options"] += f" -c statement_timeout={timeout_ms}"
    return psycopg.connect(_database_url(), **connect_kwargs)


def get_conn():
    return _get_postgres_conn() if using_postgres() else _get_sqlite_conn()


def _upgrade_sqlite_content_retention_contract(conn: sqlite3.Connection) -> None:
    """Atomically replace a legacy retention CHECK without losing valid rows."""
    schema_row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='content_retention'"
    ).fetchone()
    schema = str(schema_row["sql"] or "") if schema_row else ""
    stale_table = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='content_retention_legacy_h15'"
    ).fetchone()
    if stale_table is not None:
        raise RuntimeError("stale content retention upgrade table blocks startup")
    if "content_retention_state_check_h16" in schema:
        return
    rows = conn.execute(
        "SELECT retention_class,active_until,recovery_until,deleted_at,"
        "purge_after,purged_at FROM content_retention"
    ).fetchall()
    if any(not _valid_content_retention_row(row) for row in rows):
        raise RuntimeError("invalid content retention clocks block startup")
    conn.execute("SAVEPOINT content_retention_contract_upgrade")
    try:
        conn.execute(
            "ALTER TABLE content_retention RENAME TO content_retention_legacy_h15"
        )
        conn.execute(
            """
            CREATE TABLE content_retention (
                content_type TEXT NOT NULL
                    CHECK (content_type IN ('note','diagnosis')),
                content_id TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                retention_class TEXT NOT NULL
                    CHECK (retention_class IN ('free_7d','paid_indefinite')),
                active_until TEXT,
                recovery_until TEXT,
                deleted_at TEXT,
                purge_after TEXT,
                purged_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                contract_version TEXT NOT NULL,
                CONSTRAINT content_retention_state_check_h16 CHECK (
                    (retention_class='paid_indefinite'
                        AND active_until IS NULL
                        AND recovery_until IS NULL
                        AND (
                            (deleted_at IS NULL
                                AND purge_after IS NULL
                                AND purged_at IS NULL)
                            OR
                            (deleted_at IS NOT NULL
                                AND purge_after IS NOT NULL
                                AND noteai_retention_clock_valid(deleted_at)=1
                                AND noteai_retention_clock_valid(purge_after)=1
                                AND noteai_retention_clock_lte(
                                    deleted_at,purge_after
                                )=1
                                AND (
                                    purged_at IS NULL
                                    OR (
                                        noteai_retention_clock_valid(purged_at)=1
                                        AND noteai_retention_clock_lte(
                                            purge_after,purged_at
                                        )=1
                                    )
                                ))
                        ))
                    OR
                    (retention_class='free_7d'
                        AND active_until IS NOT NULL
                        AND recovery_until IS NOT NULL
                        AND purge_after IS NOT NULL
                        AND noteai_retention_clock_valid(active_until)=1
                        AND noteai_retention_clock_valid(recovery_until)=1
                        AND noteai_retention_clock_valid(purge_after)=1
                        AND noteai_retention_clock_lte(
                            active_until,recovery_until
                        )=1
                        AND noteai_retention_clock_lte(
                            recovery_until,purge_after
                        )=1
                        AND (
                            deleted_at IS NULL
                            OR (
                                noteai_retention_clock_valid(deleted_at)=1
                                AND noteai_retention_clock_lte(
                                    deleted_at,purge_after
                                )=1
                            )
                        )
                        AND (
                            purged_at IS NULL
                            OR (
                                noteai_retention_clock_valid(purged_at)=1
                                AND noteai_retention_clock_lte(
                                    purge_after,purged_at
                                )=1
                            )
                        ))
                ),
                PRIMARY KEY(content_type,content_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO content_retention(
                content_type,content_id,user_id,retention_class,active_until,
                recovery_until,deleted_at,purge_after,purged_at,created_at,
                updated_at,contract_version
            )
            SELECT
                content_type,content_id,user_id,retention_class,active_until,
                recovery_until,deleted_at,purge_after,purged_at,created_at,
                updated_at,contract_version
            FROM content_retention_legacy_h15
            """
        )
        conn.execute("DROP TABLE content_retention_legacy_h15")
        conn.execute(
            "CREATE INDEX idx_content_retention_user_state "
            "ON content_retention("
            "user_id,content_type,active_until,recovery_until)"
        )
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT content_retention_contract_upgrade")
        conn.execute("RELEASE SAVEPOINT content_retention_contract_upgrade")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT content_retention_contract_upgrade")


def _ensure_sqlite_content_retention_purge_guards(
    conn: sqlite3.Connection,
) -> None:
    """Reject forged purge markers outside the real delete transaction."""
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS content_retention_purge_insert_h17
        BEFORE INSERT ON content_retention
        WHEN NEW.purged_at IS NOT NULL
        BEGIN
            SELECT RAISE(
                ABORT,
                'content purge marker requires an update transition'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS content_retention_primary_insert_h20
        BEFORE INSERT ON content_retention
        WHEN (
            NEW.content_type = 'note'
            AND NOT EXISTS (
                SELECT 1 FROM notes
                WHERE id = NEW.content_id AND user_id = NEW.user_id
            )
        ) OR (
            NEW.content_type = 'diagnosis'
            AND NOT EXISTS (
                SELECT 1 FROM saved_diagnoses
                WHERE id = NEW.content_id AND user_id = NEW.user_id
            )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'content retention requires matching primary content'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS content_retention_identity_insert_h21
        BEFORE INSERT ON content_retention
        WHEN EXISTS (
            SELECT 1 FROM content_retention
            WHERE content_type = NEW.content_type
              AND content_id = NEW.content_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'content retention identity cannot be reinserted'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS content_retention_purge_update_h17
        BEFORE UPDATE OF purged_at ON content_retention
        WHEN NEW.purged_at IS NOT OLD.purged_at
        BEGIN
            SELECT CASE
                WHEN OLD.purged_at IS NOT NULL
                THEN RAISE(ABORT, 'content purge marker is immutable')
                WHEN NEW.purged_at IS NULL
                THEN RAISE(ABORT, 'content purge marker cannot be cleared')
                WHEN noteai_retention_clock_not_future(NEW.purged_at) <> 1
                THEN RAISE(ABORT, 'future content purge marker rejected')
            END;
            SELECT CASE
                WHEN NEW.content_type = 'note'
                 AND EXISTS (
                    SELECT 1 FROM notes
                    WHERE id = NEW.content_id AND user_id = NEW.user_id
                 )
                THEN RAISE(ABORT, 'content purge marker requires note deletion')
                WHEN NEW.content_type = 'diagnosis'
                 AND EXISTS (
                    SELECT 1 FROM saved_diagnoses
                    WHERE id = NEW.content_id AND user_id = NEW.user_id
                 )
                THEN RAISE(
                    ABORT,
                    'content purge marker requires diagnosis deletion'
                )
            END;
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS content_retention_identity_update_h18
        BEFORE UPDATE OF
            content_type,content_id,user_id,retention_class,created_at,
            contract_version
        ON content_retention
        WHEN NEW.content_type IS NOT OLD.content_type
          OR NEW.content_id IS NOT OLD.content_id
          OR NEW.user_id IS NOT OLD.user_id
          OR NEW.retention_class IS NOT OLD.retention_class
          OR NEW.created_at IS NOT OLD.created_at
          OR NEW.contract_version IS NOT OLD.contract_version
        BEGIN
            SELECT RAISE(
                ABORT,
                'content retention identity and contract are immutable'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS notes_retention_identity_update_h19
        BEFORE UPDATE OF id,user_id
        ON notes
        WHEN NEW.id IS NOT OLD.id
          OR NEW.user_id IS NOT OLD.user_id
        BEGIN
            SELECT RAISE(
                ABORT,
                'note retention identity is immutable'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS saved_diagnoses_retention_identity_update_h19
        BEFORE UPDATE OF id,user_id
        ON saved_diagnoses
        WHEN NEW.id IS NOT OLD.id
          OR NEW.user_id IS NOT OLD.user_id
        BEGIN
            SELECT RAISE(
                ABORT,
                'diagnosis retention identity is immutable'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS notes_retained_primary_insert_h20
        BEFORE INSERT ON notes
        WHEN EXISTS (
            SELECT 1 FROM content_retention
            WHERE content_type = 'note' AND content_id = NEW.id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'retained note identity cannot be reinserted'
            );
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS saved_diagnoses_retained_primary_insert_h20
        BEFORE INSERT ON saved_diagnoses
        WHEN EXISTS (
            SELECT 1 FROM content_retention
            WHERE content_type = 'diagnosis' AND content_id = NEW.id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'retained diagnosis identity cannot be reinserted'
            );
        END
        """
    )


def _init_sqlite() -> None:
    """创建所有表（幂等）。"""
    with closing(_get_sqlite_conn()) as conn, conn:
        conn.executescript("""
-- ── 用户表 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,          -- UUID
    username     TEXT UNIQUE NOT NULL,
    email        TEXT UNIQUE,
    password_hash TEXT NOT NULL,            -- PBKDF2-SHA256
    password_salt TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_login   TEXT,
    avatar_emoji TEXT DEFAULT '🌸',        -- 用户头像（emoji 选择）
    nickname     TEXT,                      -- 显示昵称（可与 username 不同）
    phone        TEXT,                      -- 手机号（+86 前缀，唯一约束在迁移中加）
    avatar_data  TEXT,                      -- 上传的头像 base64
    phone_verified_at TEXT,
    email_verified_at TEXT,
    password_changed_at TEXT,
    deletion_requested_at TEXT
);

-- ── 会话令牌表 ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_sessions (
    token        TEXT PRIMARY KEY,          -- secrets.token_urlsafe(32)
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    user_agent   TEXT
);

-- ── 笔记表（含版本链） ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,          -- UUID
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    domain       TEXT DEFAULT '美食',
    score        REAL,
    grade        TEXT,
    source       TEXT DEFAULT 'generate',   -- 'generate' | 'chat' | 'manual'
    parent_id    TEXT REFERENCES notes(id), -- 上一版本
    version      INT  DEFAULT 1,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC);

-- ── 对话会话表（持久化，替代内存 _chat_sessions） ───────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              TEXT PRIMARY KEY,       -- UUID
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE,
    note_id         TEXT REFERENCES notes(id),
    domain          TEXT DEFAULT '美食',
    local_time      TEXT,
    messages_json   TEXT DEFAULT '[]',      -- JSON 数组
    user_prefs_json TEXT DEFAULT '{}',      -- 用户偏好 JSON
    iteration_count INT  DEFAULT 0,
    current_score   REAL,
    generate_ctx_json TEXT,                 -- 生成时的完整上下文
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_sessions(user_id, updated_at DESC);

-- ── 用户记忆表（自建 memory 系统） ────────────────────────────────
CREATE TABLE IF NOT EXISTS user_memories (
    id           TEXT PRIMARY KEY,          -- UUID
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type  TEXT NOT NULL,
    -- memory_type 取值：
    --   'style'        写作风格偏好（如 接地气、高级感）
    --   'preference'   内容偏好（如 多图、短正文）
    --   'achievement'  成就记录（如 首次突破70分）
    --   'context'      临时上下文（生成/对话的关键决策）
    content      TEXT NOT NULL,             -- 自由文本
    importance   REAL DEFAULT 0.5,          -- 0-1，越高越优先注入
    decay_factor REAL DEFAULT 0.95,         -- 每次访问衰减（保持记忆新鲜度）
    access_count INT  DEFAULT 0,
    source_note_id TEXT REFERENCES notes(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_user ON user_memories(user_id, importance DESC);

CREATE TABLE IF NOT EXISTS user_learn (
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key     TEXT NOT NULL,
    pref_value   TEXT NOT NULL,
    confidence   REAL DEFAULT 0.5,
    update_count INTEGER DEFAULT 1,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, pref_key)
);

-- ── 成长记录表（scoring history） ───────────────────────────────────
CREATE TABLE IF NOT EXISTS growth_records (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_id      TEXT REFERENCES notes(id),
    domain       TEXT,
    score        REAL NOT NULL,
    grade        TEXT,
    action       TEXT,   -- 'diagnose' | 'generate' | 'chat_optimize'
    recorded_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_growth_user ON growth_records(user_id, recorded_at DESC);

-- ── 订阅套餐 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier         TEXT NOT NULL DEFAULT 'free',  -- 'free'|'pro'|'growth'|'pro_plus'|'studio'
    started_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,   -- 下次续费日（免费版设为 2099-01-01）
    is_active    INTEGER DEFAULT 1,
    -- 本计费周期已用配额
    used_analyze      INTEGER DEFAULT 0,
    used_generate     INTEGER DEFAULT 0,
    used_chat_rewrite INTEGER DEFAULT 0,
    used_screenshot   INTEGER DEFAULT 0,
    used_monthly_credits REAL DEFAULT 0,
    period_start TEXT NOT NULL    -- 本周期开始时间（每月重置）
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);

-- ── 用量明细 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usage_records (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    operation    TEXT NOT NULL,  -- 'analyze'|'generate'|'chat_rewrite'|'chat_fast'|'diagnose'|'screenshot'
    tokens_in    INTEGER DEFAULT 0,
    tokens_out   INTEGER DEFAULT 0,
    cost_rmb     REAL    DEFAULT 0,
    estimated_cost_rmb REAL DEFAULT 0,
    actual_model_cost_rmb REAL DEFAULT 0,
    model_calls  INTEGER DEFAULT 0,
    model_names  TEXT    DEFAULT '',
    cost_mode    TEXT    DEFAULT 'estimated',
    credits_used REAL    DEFAULT 0,   -- 0=套餐覆盖, >0=积分扣除
    source       TEXT    DEFAULT 'subscription',  -- 'subscription'|'credits'|'free'
    recorded_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(user_id, recorded_at DESC);

-- ── 模型调用成本审计明细（不存 Prompt、正文或 reasoning） ────────
CREATE TABLE IF NOT EXISTS model_usage_records (
    id                           TEXT PRIMARY KEY,
    usage_record_id              TEXT NOT NULL REFERENCES usage_records(id) ON DELETE CASCADE,
    provider                     TEXT NOT NULL,
    model                        TEXT NOT NULL,
    input_tokens                 INTEGER DEFAULT 0,
    unclassified_input_tokens    INTEGER DEFAULT 0,
    cache_read_input_tokens      INTEGER DEFAULT 0,
    cache_write_input_tokens     INTEGER DEFAULT 0,
    cache_write_5m_tokens        INTEGER DEFAULT 0,
    cache_write_1h_tokens        INTEGER DEFAULT 0,
    cache_write_unknown_ttl_tokens INTEGER DEFAULT 0,
    output_tokens                INTEGER DEFAULT 0,
    input_price_per_1m           REAL,
    cache_read_price_per_1m      REAL,
    cache_write_5m_price_per_1m  REAL,
    cache_write_1h_price_per_1m  REAL,
    output_price_per_1m          REAL,
    price_currency               TEXT NOT NULL,
    usd_cny                      REAL NOT NULL,
    price_version                TEXT NOT NULL,
    known_cost_rmb               REAL DEFAULT 0,
    pricing_status               TEXT NOT NULL,
    usage_status                 TEXT NOT NULL,
    recorded_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_usage_parent ON model_usage_records(usage_record_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_model_usage_model ON model_usage_records(provider, model, recorded_at);

-- ── 积分账户 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credits (
    user_id         TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    balance         REAL DEFAULT 0,
    total_purchased REAL DEFAULT 0,
    total_used      REAL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

-- ── 积分流水 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_transactions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    type          TEXT NOT NULL,   -- 'topup'|'usage'|'refund'|'gift'
    amount        REAL NOT NULL,   -- 正=充入 负=扣除
    balance_after REAL NOT NULL,
    description   TEXT,
    paid_rmb      REAL DEFAULT 0,  -- 真实支付金额；赠送/消耗为0
    package_id    TEXT DEFAULT '',
    payment_ref   TEXT DEFAULT '',
    recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ctxn_user ON credit_transactions(user_id, recorded_at DESC);

-- ── 正式支付合同（仅整数分、摘要和固定状态）──────────────────────
CREATE TABLE IF NOT EXISTS payment_orders (
    id                   TEXT PRIMARY KEY CHECK (
                             length(id)=36 AND length(replace(id,'-',''))=32
                             AND id NOT GLOB '*[^0-9a-f-]*'
                         ),
    user_id              TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_hash         TEXT NOT NULL CHECK (
                             length(subject_hash)=64
                             AND subject_hash NOT GLOB '*[^0-9a-f]*'
                         ),
    product_kind         TEXT NOT NULL CHECK (
                             product_kind IN ('subscription','credit_package')
                         ),
    product_id           TEXT NOT NULL CHECK (
                             product_id IN (
                                 'pro','growth','pro_plus','studio',
                                 'starter','creator'
                             )
                         ),
    catalog_version      TEXT NOT NULL CHECK (
                             catalog_version='first-launch-v1-2026-07-26'
                         ),
    amount_fen           INTEGER NOT NULL CHECK (
                             amount_fen BETWEEN 1 AND 100000000
                         ),
    currency             TEXT NOT NULL CHECK (currency='CNY'),
    provider             TEXT NOT NULL CHECK (provider='adapay'),
    provider_mode        TEXT NOT NULL CHECK (
                             provider_mode IN ('mock','live')
                         ),
    merchant_order_no    TEXT NOT NULL UNIQUE,
    provider_payment_id TEXT UNIQUE,
    app_id_hash          TEXT NOT NULL CHECK (
                             length(app_id_hash)=64
                             AND app_id_hash NOT GLOB '*[^0-9a-f]*'
                         ),
    idempotency_key_hash TEXT NOT NULL CHECK (
                             length(idempotency_key_hash)=64
                             AND idempotency_key_hash NOT GLOB '*[^0-9a-f]*'
                         ),
    request_hash         TEXT NOT NULL CHECK (
                             length(request_hash)=64
                             AND request_hash NOT GLOB '*[^0-9a-f]*'
                         ),
    payment_status       TEXT NOT NULL CHECK (
                             payment_status IN (
                                 'created','pending','succeeded','failed',
                                 'closed','needs_manual'
                             )
                         ),
    entitlement_status   TEXT NOT NULL CHECK (
                             entitlement_status IN (
                                 'pending','applied','reversed','needs_manual'
                             )
                         ),
    entitlement_ref      TEXT,
    refund_status        TEXT NOT NULL CHECK (
                             refund_status IN (
                                 'none','pending','refunded','needs_manual'
                             )
                         ),
    refunded_fen         INTEGER NOT NULL DEFAULT 0 CHECK (
                             refunded_fen BETWEEN 0 AND amount_fen
                         ),
    refund_count         INTEGER NOT NULL DEFAULT 0 CHECK (
                             refund_count BETWEEN 0 AND 1
                         ),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    succeeded_at         TEXT,
    terminal_at          TEXT,
    UNIQUE(user_id,idempotency_key_hash),
    CHECK (
        (product_kind='subscription'
            AND (
                (product_id='pro' AND amount_fen=9900)
                OR (product_id='growth' AND amount_fen=19900)
                OR (product_id='pro_plus' AND amount_fen=29900)
                OR (product_id='studio' AND amount_fen=39900)
            ))
        OR
        (product_kind='credit_package'
            AND (
                (product_id='starter' AND amount_fen=1200)
                OR (product_id='creator' AND amount_fen=3900)
                OR (product_id='growth' AND amount_fen=10900)
                OR (product_id='studio' AND amount_fen=27900)
            ))
    ),
    CHECK (
        entitlement_status='pending'
        OR payment_status='succeeded'
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_orders_user
    ON payment_orders(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_orders_state
    ON payment_orders(payment_status,entitlement_status,updated_at);

CREATE TABLE IF NOT EXISTS payment_events (
    id                       TEXT PRIMARY KEY,
    provider_event_id_hash   TEXT NOT NULL UNIQUE CHECK (
                                 length(provider_event_id_hash)=64
                                 AND provider_event_id_hash
                                     NOT GLOB '*[^0-9a-f]*'
                             ),
    event_type               TEXT NOT NULL,
    payload_sha256           TEXT NOT NULL CHECK (
                                 length(payload_sha256)=64
                                 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
                             ),
    signature_sha256         TEXT NOT NULL CHECK (
                                 length(signature_sha256)=64
                                 AND signature_sha256 NOT GLOB '*[^0-9a-f]*'
                             ),
    app_id_hash              TEXT NOT NULL CHECK (
                                 length(app_id_hash)=64
                                 AND app_id_hash NOT GLOB '*[^0-9a-f]*'
                             ),
    prod_mode                INTEGER NOT NULL CHECK (prod_mode IN (0,1)),
    provider_created_at      INTEGER NOT NULL,
    processing_state         TEXT NOT NULL CHECK (
                                 processing_state IN (
                                     'accepted','processed','ignored',
                                     'needs_manual'
                                 )
                             ),
    reason_code              TEXT NOT NULL,
    order_id                 TEXT REFERENCES payment_orders(id),
    refund_id                TEXT,
    received_at              TEXT NOT NULL,
    processed_at             TEXT
);
CREATE INDEX IF NOT EXISTS idx_payment_events_state
    ON payment_events(processing_state,received_at);

CREATE TABLE IF NOT EXISTS payment_refunds (
    id                   TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL REFERENCES payment_orders(id)
                         ON DELETE RESTRICT,
    merchant_refund_no   TEXT NOT NULL UNIQUE,
    provider_refund_id   TEXT UNIQUE,
    amount_fen           INTEGER NOT NULL CHECK (
                             amount_fen BETWEEN 1 AND 100000000
                         ),
    currency             TEXT NOT NULL CHECK (currency='CNY'),
    status               TEXT NOT NULL CHECK (
                             status IN (
                                 'requested','pending','succeeded','failed',
                                 'needs_manual'
                             )
                         ),
    reason_code          TEXT NOT NULL CHECK (
                             reason_code IN (
                                 'customer_request','service_not_delivered',
                                 'duplicate_payment','fraud_review'
                             )
                         ),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    terminal_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_payment_refunds_order
    ON payment_refunds(order_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_refunds_one_v1
    ON payment_refunds(order_id);

CREATE TABLE IF NOT EXISTS payment_cash_ledger (
    id               TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES payment_orders(id)
                     ON DELETE RESTRICT,
    refund_id        TEXT REFERENCES payment_refunds(id)
                     ON DELETE RESTRICT,
    entry_type       TEXT NOT NULL CHECK (
                         entry_type IN (
                             'payment_received','payment_received_unmatched',
                             'refund_paid','refund_paid_unmatched'
                         )
                     ),
    amount_fen       INTEGER NOT NULL CHECK (
                         amount_fen BETWEEN -100000000 AND 100000000
                         AND amount_fen<>0
                     ),
    currency         TEXT NOT NULL CHECK (currency='CNY'),
    source_event_id  TEXT NOT NULL UNIQUE
                     REFERENCES payment_events(id) ON DELETE RESTRICT,
    recorded_at      TEXT NOT NULL,
    CHECK (
        (entry_type LIKE 'payment_%' AND amount_fen>0 AND refund_id IS NULL)
        OR
        (entry_type LIKE 'refund_%' AND amount_fen<0 AND refund_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_cash_recorded
    ON payment_cash_ledger(recorded_at,entry_type);
CREATE INDEX IF NOT EXISTS idx_payment_cash_order
    ON payment_cash_ledger(order_id,recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_cash_one_receipt_v1
    ON payment_cash_ledger(order_id)
    WHERE entry_type IN (
        'payment_received','payment_received_unmatched'
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_cash_one_refund_v1
    ON payment_cash_ledger(refund_id)
    WHERE entry_type IN ('refund_paid','refund_paid_unmatched');

CREATE TABLE IF NOT EXISTS payment_entitlement_ledger (
    id                TEXT PRIMARY KEY,
    order_id          TEXT NOT NULL REFERENCES payment_orders(id)
                      ON DELETE RESTRICT,
    refund_id         TEXT REFERENCES payment_refunds(id)
                      ON DELETE RESTRICT,
    entry_type        TEXT NOT NULL CHECK (
                          entry_type IN (
                              'credit_grant','credit_reversal',
                              'subscription_grant','subscription_reversal'
                          )
                      ),
    product_kind      TEXT NOT NULL CHECK (
                          product_kind IN ('subscription','credit_package')
                      ),
    product_id        TEXT NOT NULL,
    quantity_milli    INTEGER NOT NULL CHECK (quantity_milli<>0),
    subscription_id   TEXT,
    source_event_id   TEXT NOT NULL UNIQUE
                      REFERENCES payment_events(id) ON DELETE RESTRICT,
    recorded_at       TEXT NOT NULL,
    CHECK (
        (entry_type LIKE '%_grant' AND quantity_milli>0 AND refund_id IS NULL)
        OR
        (entry_type LIKE '%_reversal' AND quantity_milli<0
            AND refund_id IS NOT NULL)
    ),
    CHECK (
        (product_kind='subscription' AND subscription_id IS NOT NULL)
        OR
        (product_kind='credit_package' AND subscription_id IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_entitlement_order
    ON payment_entitlement_ledger(order_id,recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_entitlement_once_v1
    ON payment_entitlement_ledger(order_id,entry_type);

CREATE TABLE IF NOT EXISTS payment_credit_positions (
    order_id         TEXT PRIMARY KEY REFERENCES payment_orders(id)
                     ON DELETE RESTRICT,
    user_id          TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_hash     TEXT NOT NULL CHECK (
                         length(subject_hash)=64
                         AND subject_hash NOT GLOB '*[^0-9a-f]*'
                     ),
    granted_milli    INTEGER NOT NULL CHECK (granted_milli>0),
    remaining_milli  INTEGER NOT NULL CHECK (
                         remaining_milli BETWEEN 0 AND granted_milli
                     ),
    state            TEXT NOT NULL CHECK (
                         state IN ('active','consumed','reversed')
                     ),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    CHECK (
        (state='active' AND remaining_milli>0)
        OR (state IN ('consumed','reversed') AND remaining_milli=0)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_credit_positions_user
    ON payment_credit_positions(user_id,state,created_at);

CREATE TABLE IF NOT EXISTS payment_credit_consumptions (
    id            TEXT PRIMARY KEY,
    order_id      TEXT NOT NULL REFERENCES payment_credit_positions(order_id)
                  ON DELETE RESTRICT,
    usage_id      TEXT NOT NULL,
    amount_milli  INTEGER NOT NULL CHECK (amount_milli>0),
    state         TEXT NOT NULL CHECK (state IN ('consumed','restored')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(order_id,usage_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_credit_consumptions_usage
    ON payment_credit_consumptions(usage_id,state);

CREATE TABLE IF NOT EXISTS payment_reconciliation_runs (
    id                    TEXT PRIMARY KEY,
    provider              TEXT NOT NULL CHECK (provider='adapay'),
    provider_mode         TEXT NOT NULL CHECK (
                              provider_mode IN ('mock','live')
                          ),
    bill_date             TEXT NOT NULL,
    source_sha256         TEXT NOT NULL CHECK (
                              length(source_sha256)=64
                              AND source_sha256 NOT GLOB '*[^0-9a-f]*'
                          ),
    row_count             INTEGER NOT NULL CHECK (
                              row_count BETWEEN 0 AND 10000
                          ),
    payment_total_fen     INTEGER NOT NULL CHECK (payment_total_fen>=0),
    refund_total_fen      INTEGER NOT NULL CHECK (refund_total_fen>=0),
    discrepancy_count     INTEGER NOT NULL CHECK (discrepancy_count>=0),
    status                TEXT NOT NULL CHECK (
                              status IN ('matched','discrepancies','needs_manual')
                          ),
    created_at            TEXT NOT NULL,
    completed_at          TEXT NOT NULL,
    UNIQUE(provider,provider_mode,bill_date,source_sha256)
);
CREATE INDEX IF NOT EXISTS idx_payment_reconciliation_date
    ON payment_reconciliation_runs(provider_mode,bill_date);

CREATE TABLE IF NOT EXISTS payment_reconciliation_items (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES payment_reconciliation_runs(id)
                      ON DELETE RESTRICT,
    entry_kind        TEXT NOT NULL CHECK (
                          entry_kind IN ('payment','refund')
                      ),
    reference_hash    TEXT NOT NULL CHECK (
                          length(reference_hash)=64
                          AND reference_hash NOT GLOB '*[^0-9a-f]*'
                      ),
    issue_code        TEXT NOT NULL CHECK (
                          issue_code IN (
                              'missing_local','missing_provider',
                              'amount_mismatch','status_mismatch'
                          )
                      ),
    local_fen         INTEGER,
    provider_fen      INTEGER,
    resolution_state TEXT NOT NULL CHECK (
                          resolution_state IN ('open','accepted','resolved')
                      ),
    created_at        TEXT NOT NULL,
    UNIQUE(run_id,entry_kind,reference_hash,issue_code)
);

CREATE TABLE IF NOT EXISTS payment_settlement_summaries (
    id               TEXT PRIMARY KEY,
    provider         TEXT NOT NULL CHECK (provider='adapay'),
    provider_mode    TEXT NOT NULL CHECK (
                         provider_mode IN ('mock','live')
                     ),
    settlement_date  TEXT NOT NULL,
    source_sha256    TEXT NOT NULL CHECK (
                         length(source_sha256)=64
                         AND source_sha256 NOT GLOB '*[^0-9a-f]*'
                     ),
    gross_fen        INTEGER NOT NULL CHECK (gross_fen>=0),
    refund_fen       INTEGER NOT NULL CHECK (refund_fen>=0),
    fee_fen          INTEGER NOT NULL CHECK (fee_fen>=0),
    net_fen          INTEGER NOT NULL CHECK (net_fen>=0),
    status           TEXT NOT NULL CHECK (
                         status IN ('verified','needs_manual')
                     ),
    created_at       TEXT NOT NULL,
    UNIQUE(provider,provider_mode,settlement_date,source_sha256),
    CHECK (gross_fen-refund_fen-fee_fen=net_fen)
);

CREATE TRIGGER IF NOT EXISTS payment_orders_identity_immutable_v1
BEFORE UPDATE OF
    id,subject_hash,product_kind,product_id,catalog_version,amount_fen,
    currency,provider,provider_mode,merchant_order_no,app_id_hash,
    idempotency_key_hash,request_hash,created_at
ON payment_orders
BEGIN
    SELECT RAISE(ABORT,'payment order identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_orders_user_join_immutable_v1
BEFORE UPDATE OF user_id ON payment_orders
WHEN
    OLD.user_id IS NULL
    OR NEW.user_id IS NOT NULL
    OR NEW.provider_payment_id IS NOT OLD.provider_payment_id
    OR NEW.payment_status IS NOT OLD.payment_status
    OR NEW.entitlement_status IS NOT OLD.entitlement_status
    OR NEW.entitlement_ref IS NOT OLD.entitlement_ref
    OR NEW.refund_status IS NOT OLD.refund_status
    OR NEW.refunded_fen IS NOT OLD.refunded_fen
    OR NEW.refund_count IS NOT OLD.refund_count
    OR NEW.updated_at IS NOT OLD.updated_at
    OR NEW.succeeded_at IS NOT OLD.succeeded_at
    OR NEW.terminal_at IS NOT OLD.terminal_at
BEGIN
    SELECT RAISE(ABORT,'payment order user join is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_orders_transition_v1
BEFORE UPDATE ON payment_orders
WHEN
    (OLD.payment_status='created'
        AND NEW.payment_status NOT IN (
            'created','pending','succeeded','failed','closed','needs_manual'
        ))
    OR
    (OLD.payment_status='pending'
        AND NEW.payment_status NOT IN (
            'pending','succeeded','failed','closed','needs_manual'
        ))
    OR
    (OLD.payment_status='succeeded'
        AND NEW.payment_status<>'succeeded')
    OR
    (OLD.payment_status IN ('failed','closed')
        AND NEW.payment_status NOT IN (OLD.payment_status,'needs_manual'))
    OR
    (OLD.payment_status='needs_manual'
        AND NEW.payment_status<>'needs_manual')
    OR
    (OLD.entitlement_status='pending'
        AND NEW.entitlement_status NOT IN (
            'pending','applied','needs_manual'
        ))
    OR
    (OLD.entitlement_status='applied'
        AND NEW.entitlement_status NOT IN (
            'applied','reversed','needs_manual'
        ))
    OR
    (OLD.entitlement_status='reversed'
        AND NEW.entitlement_status<>'reversed')
    OR
    (OLD.refund_status='none'
        AND NEW.refund_status NOT IN ('none','pending','needs_manual'))
    OR
    (OLD.refund_status='pending'
        AND NEW.refund_status NOT IN (
            'pending','refunded','needs_manual'
        ))
    OR
    (OLD.refund_status='refunded'
        AND NEW.refund_status<>'refunded')
    OR
    (OLD.refund_status='needs_manual'
        AND NEW.refund_status<>'needs_manual')
    OR NEW.refunded_fen<OLD.refunded_fen
    OR NEW.refund_count<OLD.refund_count
    OR (
        OLD.provider_payment_id IS NOT NULL
        AND NEW.provider_payment_id IS NOT OLD.provider_payment_id
    )
BEGIN
    SELECT RAISE(ABORT,'invalid payment order transition');
END;

CREATE TRIGGER IF NOT EXISTS payment_events_identity_immutable_v1
BEFORE UPDATE OF
    id,provider_event_id_hash,event_type,payload_sha256,signature_sha256,
    app_id_hash,prod_mode,provider_created_at,received_at
ON payment_events
BEGIN
    SELECT RAISE(ABORT,'payment event identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_events_transition_v1
BEFORE UPDATE ON payment_events
WHEN
    (OLD.processing_state<>'accepted'
        AND NEW.processing_state<>OLD.processing_state)
    OR
    (OLD.processing_state='accepted'
        AND NEW.processing_state NOT IN (
            'accepted','processed','ignored','needs_manual'
        ))
BEGIN
    SELECT RAISE(ABORT,'invalid payment event transition');
END;

CREATE TRIGGER IF NOT EXISTS payment_refunds_identity_immutable_v1
BEFORE UPDATE OF
    id,order_id,merchant_refund_no,amount_fen,currency,reason_code,created_at
ON payment_refunds
BEGIN
    SELECT RAISE(ABORT,'payment refund identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_refunds_insert_guard_v1
BEFORE INSERT ON payment_refunds
WHEN
    NOT EXISTS (
        SELECT 1 FROM payment_orders
        WHERE id=NEW.order_id
          AND amount_fen=NEW.amount_fen
          AND payment_status='succeeded'
          AND entitlement_status='applied'
          AND refunded_fen=0
    )
BEGIN
    SELECT RAISE(ABORT,'invalid full refund intent');
END;

CREATE TRIGGER IF NOT EXISTS payment_refunds_transition_v1
BEFORE UPDATE ON payment_refunds
WHEN
    (OLD.status='requested'
        AND NEW.status NOT IN (
            'requested','pending','succeeded','failed','needs_manual'
        ))
    OR
    (OLD.status='pending'
        AND NEW.status NOT IN (
            'pending','succeeded','failed','needs_manual'
        ))
    OR
    (OLD.status='succeeded'
        AND NEW.status<>'succeeded')
    OR
    (OLD.status='failed'
        AND NEW.status NOT IN ('failed','needs_manual'))
    OR
    (OLD.status='needs_manual'
        AND NEW.status<>'needs_manual')
    OR (
        OLD.provider_refund_id IS NOT NULL
        AND NEW.provider_refund_id IS NOT OLD.provider_refund_id
    )
BEGIN
    SELECT RAISE(ABORT,'invalid payment refund transition');
END;

CREATE TRIGGER IF NOT EXISTS payment_cash_ledger_no_update_v1
BEFORE UPDATE ON payment_cash_ledger
BEGIN
    SELECT RAISE(ABORT,'payment cash ledger is append only');
END;
CREATE TRIGGER IF NOT EXISTS payment_cash_ledger_no_delete_v1
BEFORE DELETE ON payment_cash_ledger
BEGIN
    SELECT RAISE(ABORT,'payment cash ledger is append only');
END;

CREATE TRIGGER IF NOT EXISTS payment_entitlement_ledger_no_update_v1
BEFORE UPDATE ON payment_entitlement_ledger
BEGIN
    SELECT RAISE(ABORT,'payment entitlement ledger is append only');
END;
CREATE TRIGGER IF NOT EXISTS payment_entitlement_ledger_no_delete_v1
BEFORE DELETE ON payment_entitlement_ledger
BEGIN
    SELECT RAISE(ABORT,'payment entitlement ledger is append only');
END;

CREATE TRIGGER IF NOT EXISTS payment_credit_position_identity_v1
BEFORE UPDATE OF order_id,subject_hash,granted_milli,created_at
ON payment_credit_positions
BEGIN
    SELECT RAISE(ABORT,'payment credit position identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_credit_position_user_identity_v1
BEFORE UPDATE OF user_id ON payment_credit_positions
WHEN
    (OLD.user_id IS NULL AND NEW.user_id IS NOT NULL)
    OR (
        OLD.user_id IS NOT NULL
        AND NEW.user_id IS NOT NULL
        AND NEW.user_id IS NOT OLD.user_id
    )
BEGIN
    SELECT RAISE(ABORT,'payment credit position user is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_credit_consumption_identity_v1
BEFORE UPDATE OF id,order_id,usage_id,amount_milli,created_at
ON payment_credit_consumptions
BEGIN
    SELECT RAISE(ABORT,'payment credit consumption identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_credit_consumption_transition_v1
BEFORE UPDATE ON payment_credit_consumptions
WHEN
    (OLD.state='consumed'
        AND NEW.state NOT IN ('consumed','restored'))
    OR
    (OLD.state='restored' AND NEW.state<>'restored')
BEGIN
    SELECT RAISE(ABORT,'invalid payment credit consumption transition');
END;

CREATE TRIGGER IF NOT EXISTS payment_settlement_no_update_v1
BEFORE UPDATE ON payment_settlement_summaries
BEGIN
    SELECT RAISE(ABORT,'payment settlement is immutable');
END;
CREATE TRIGGER IF NOT EXISTS payment_settlement_no_delete_v1
BEFORE DELETE ON payment_settlement_summaries
BEGIN
    SELECT RAISE(ABORT,'payment settlement is immutable');
END;

CREATE TRIGGER IF NOT EXISTS payment_reconciliation_run_no_update_v1
BEFORE UPDATE ON payment_reconciliation_runs
BEGIN
    SELECT RAISE(ABORT,'payment reconciliation evidence is immutable');
END;
CREATE TRIGGER IF NOT EXISTS payment_reconciliation_run_no_delete_v1
BEFORE DELETE ON payment_reconciliation_runs
BEGIN
    SELECT RAISE(ABORT,'payment reconciliation evidence is immutable');
END;
CREATE TRIGGER IF NOT EXISTS payment_reconciliation_item_no_update_v1
BEFORE UPDATE ON payment_reconciliation_items
BEGIN
    SELECT RAISE(ABORT,'payment reconciliation evidence is immutable');
END;
CREATE TRIGGER IF NOT EXISTS payment_reconciliation_item_no_delete_v1
BEFORE DELETE ON payment_reconciliation_items
BEGIN
    SELECT RAISE(ABORT,'payment reconciliation evidence is immutable');
END;

-- ── 付费请求幂等账本（仅保存摘要，不保存 raw key 或请求正文）──────────
CREATE TABLE IF NOT EXISTS idempotency_requests (
    id                   TEXT PRIMARY KEY,
    user_id              TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation            TEXT NOT NULL,
    key_hash             TEXT NOT NULL,
    payload_hash         TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'completed', 'failed')),
    lease_token_hash     TEXT NOT NULL,
    lease_expires_at     TEXT NOT NULL,
    usage_id             TEXT,
    charged_subscription_id TEXT,
    charged_period_start TEXT,
    charge_source        TEXT DEFAULT '',
    credits_used         REAL DEFAULT 0,
    monthly_credits_used REAL DEFAULT 0,
    wallet_credits_used  REAL DEFAULT 0,
    usage_created        INTEGER DEFAULT 0,
    charge_applied       INTEGER DEFAULT 0,
    refund_applied       INTEGER DEFAULT 0,
    complete_applied     INTEGER DEFAULT 0,
    failure_code         TEXT DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    usage_created_at     TEXT,
    charged_at           TEXT,
    refunded_at          TEXT,
    completed_at         TEXT,
    failed_at            TEXT,
    UNIQUE(user_id, operation, key_hash)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_status_lease
    ON idempotency_requests(status, lease_expires_at);

-- ── 持久 AI operation queue（只存摘要、状态和计数）────────
CREATE TABLE IF NOT EXISTS ai_operations (
    id                     TEXT NOT NULL PRIMARY KEY CHECK (
                               length(id) = 36
                               AND length(replace(id, '-', '')) = 32
                               AND substr(id, 9, 1) = '-'
                               AND substr(id, 14, 1) = '-'
                               AND substr(id, 19, 1) = '-'
                               AND substr(id, 24, 1) = '-'
                               AND id NOT GLOB '*[^0-9a-f-]*'
                           ),
    subject_hash           TEXT NOT NULL CHECK (
                               length(subject_hash) = 64
                               AND subject_hash NOT GLOB '*[^0-9a-f]*'
                           ),
    request_hash           TEXT NOT NULL CHECK (
                               length(request_hash) = 64
                               AND request_hash NOT GLOB '*[^0-9a-f]*'
                           ),
    operation_kind         TEXT NOT NULL
                           CHECK (operation_kind IN ('analyze', 'generate', 'chat_rewrite')),
    status                 TEXT NOT NULL DEFAULT 'queued'
                           CHECK (status IN (
                               'queued', 'running', 'succeeded', 'failed',
                               'outcome_unknown', 'cancelled'
                           )),
    provider_phase         TEXT NOT NULL DEFAULT 'not_started'
                           CHECK (provider_phase IN (
                               'not_started', 'provider_started', 'provider_terminal'
                           )),
    priority               INTEGER NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 9),
    available_at           TEXT NOT NULL,
    lease_owner_hash       TEXT CHECK (
                               lease_owner_hash IS NULL OR (
                                   length(lease_owner_hash) = 64
                                   AND lease_owner_hash NOT GLOB '*[^0-9a-f]*'
                               )
                           ),
    lease_fence            INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
    lease_expires_at       TEXT,
    heartbeat_at           TEXT,
    claim_count            INTEGER NOT NULL DEFAULT 0 CHECK (claim_count >= 0),
    provider_attempt_count INTEGER NOT NULL DEFAULT 0
                           CHECK (provider_attempt_count >= 0),
    event_sequence         INTEGER NOT NULL DEFAULT 0 CHECK (event_sequence >= 0),
    result_hash            TEXT CHECK (
                               result_hash IS NULL OR (
                                   length(result_hash) = 64
                                   AND result_hash NOT GLOB '*[^0-9a-f]*'
                               )
                           ),
    result_count           INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    started_at             TEXT,
    terminal_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_operations_claim
    ON ai_operations(status, available_at, lease_expires_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_operations_subject
    ON ai_operations(subject_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_operation_events (
    id               TEXT NOT NULL PRIMARY KEY,
    operation_id     TEXT NOT NULL REFERENCES ai_operations(id) ON DELETE CASCADE,
    sequence         INTEGER NOT NULL CHECK (sequence > 0),
    event_type       TEXT NOT NULL
                     CHECK (event_type IN (
                         'enqueued', 'claimed', 'lease_taken_over', 'progress',
                         'provider_started', 'provider_terminal', 'succeeded',
                         'failed', 'outcome_unknown', 'cancelled'
                     )),
    operation_status TEXT NOT NULL
                     CHECK (operation_status IN (
                         'queued', 'running', 'succeeded', 'failed',
                         'outcome_unknown', 'cancelled'
                     )),
    fence            INTEGER NOT NULL CHECK (fence >= 0),
    provider         TEXT CHECK (provider IS NULL OR provider IN ('claude', 'kimi')),
    detail_hash      TEXT CHECK (
                         detail_hash IS NULL OR (
                             length(detail_hash) = 64
                             AND detail_hash NOT GLOB '*[^0-9a-f]*'
                         )
                     ),
    item_count       INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    recorded_at      TEXT NOT NULL,
    UNIQUE(operation_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_ai_operation_events_replay
    ON ai_operation_events(operation_id, sequence);

CREATE TABLE IF NOT EXISTS ai_provider_attempts (
    id             TEXT NOT NULL PRIMARY KEY,
    operation_id   TEXT NOT NULL REFERENCES ai_operations(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    fence          INTEGER NOT NULL CHECK (fence > 0),
    provider       TEXT NOT NULL CHECK (provider IN ('claude', 'kimi')),
    state          TEXT NOT NULL
                   CHECK (state IN (
                       'provider_started', 'provider_succeeded',
                       'provider_failed', 'outcome_unknown'
                   )),
    request_hash   TEXT NOT NULL CHECK (
                       length(request_hash) = 64
                       AND request_hash NOT GLOB '*[^0-9a-f]*'
                   ),
    model_hash     TEXT NOT NULL CHECK (
                       length(model_hash) = 64
                       AND model_hash NOT GLOB '*[^0-9a-f]*'
                   ),
    response_hash  TEXT CHECK (
                       response_hash IS NULL OR (
                           length(response_hash) = 64
                           AND response_hash NOT GLOB '*[^0-9a-f]*'
                       )
                   ),
    input_count    INTEGER NOT NULL DEFAULT 0 CHECK (input_count >= 0),
    output_count   INTEGER NOT NULL DEFAULT 0 CHECK (output_count >= 0),
    started_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    terminal_at    TEXT,
    UNIQUE(operation_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_ai_provider_attempts_operation
    ON ai_provider_attempts(operation_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_ai_provider_attempts_provider
    ON ai_provider_attempts(provider, state, started_at);

CREATE TABLE IF NOT EXISTS ai_operation_admissions (
    operation_id           TEXT NOT NULL PRIMARY KEY
                           REFERENCES ai_operations(id) ON DELETE RESTRICT,
    idempotency_request_id TEXT NOT NULL UNIQUE
                           REFERENCES idempotency_requests(id) ON DELETE RESTRICT,
    created_at             TEXT NOT NULL
);

-- Durable AI storage/outbox/settlement contract. Only opaque identifiers,
-- digests, bounded counters, fixed states and clocks may cross this boundary.
CREATE TABLE IF NOT EXISTS ai_payload_refs (
    id                  TEXT NOT NULL PRIMARY KEY CHECK (
                            length(id) = 36
                            AND length(replace(id, '-', '')) = 32
                            AND substr(id, 9, 1) = '-'
                            AND substr(id, 14, 1) = '-'
                            AND substr(id, 19, 1) = '-'
                            AND substr(id, 24, 1) = '-'
                            AND id NOT GLOB '*[^0-9a-f-]*'
                        ),
    operation_id        TEXT NOT NULL
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    subject_hash        TEXT NOT NULL CHECK (
                            length(subject_hash) = 64
                            AND subject_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    purpose             TEXT NOT NULL CHECK (purpose IN ('request','result')),
    object_key_hash     TEXT NOT NULL CHECK (
                            length(object_key_hash) = 64
                            AND object_key_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    content_sha256      TEXT NOT NULL CHECK (
                            length(content_sha256) = 64
                            AND content_sha256 NOT GLOB '*[^0-9a-f]*'
                        ),
    size_bytes          INTEGER NOT NULL CHECK (size_bytes BETWEEN 1 AND 134217728),
    item_count          INTEGER NOT NULL CHECK (item_count BETWEEN 0 AND 1000),
    schema_version      INTEGER NOT NULL CHECK (schema_version BETWEEN 1 AND 16),
    encryption_mode     TEXT NOT NULL
                        CHECK (encryption_mode IN ('provider_managed','envelope_aes256')),
    key_epoch_hash      TEXT NOT NULL CHECK (
                            length(key_epoch_hash) = 64
                            AND key_epoch_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    state               TEXT NOT NULL CHECK (state IN ('ready','expired','deleted')),
    expires_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    ready_at            TEXT NOT NULL,
    deleted_at          TEXT,
    UNIQUE(operation_id, purpose),
    CHECK (
        (state = 'ready' AND deleted_at IS NULL)
        OR (state IN ('expired','deleted') AND deleted_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_ai_payload_refs_lifecycle
    ON ai_payload_refs(state, expires_at, purpose);
CREATE INDEX IF NOT EXISTS idx_ai_payload_refs_subject
    ON ai_payload_refs(subject_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS private_media_refs (
    id                  TEXT NOT NULL PRIMARY KEY CHECK (
                            length(id) = 36
                            AND length(replace(id, '-', '')) = 32
                            AND substr(id, 9, 1) = '-'
                            AND substr(id, 14, 1) = '-'
                            AND substr(id, 19, 1) = '-'
                            AND substr(id, 24, 1) = '-'
                            AND id NOT GLOB '*[^0-9a-f-]*'
                        ),
    subject_hash        TEXT NOT NULL CHECK (
                            length(subject_hash) = 64
                            AND subject_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    purpose             TEXT NOT NULL CHECK (purpose IN ('image','video_frames')),
    content_type        TEXT NOT NULL CHECK (
                            (purpose = 'image' AND content_type IN (
                                'image/jpeg','image/png','image/webp'
                            ))
                            OR (
                                purpose = 'video_frames'
                                AND content_type = 'application/vnd.noteai.video-frames+zip'
                            )
                        ),
    object_key_hash     TEXT NOT NULL CHECK (
                            length(object_key_hash) = 64
                            AND object_key_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    content_sha256      TEXT NOT NULL CHECK (
                            length(content_sha256) = 64
                            AND content_sha256 NOT GLOB '*[^0-9a-f]*'
                        ),
    size_bytes          INTEGER NOT NULL CHECK (
                            (purpose = 'image' AND size_bytes BETWEEN 1 AND 10485760)
                            OR (
                                purpose = 'video_frames'
                                AND size_bytes BETWEEN 1 AND 67108864
                            )
                        ),
    item_count          INTEGER NOT NULL CHECK (
                            (purpose = 'image' AND item_count = 1)
                            OR (purpose = 'video_frames' AND item_count BETWEEN 1 AND 100)
                        ),
    schema_version      INTEGER NOT NULL CHECK (schema_version BETWEEN 1 AND 16),
    encryption_mode     TEXT NOT NULL CHECK (
                            encryption_mode IN ('provider_managed','envelope_aes256')
                        ),
    key_epoch_hash      TEXT NOT NULL CHECK (
                            length(key_epoch_hash) = 64
                            AND key_epoch_hash NOT GLOB '*[^0-9a-f]*'
                        ),
    state               TEXT NOT NULL CHECK (state IN ('ready','expired','deleted')),
    expires_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    ready_at            TEXT NOT NULL,
    deleted_at          TEXT,
    CHECK (
        (state = 'ready' AND deleted_at IS NULL)
        OR (state IN ('expired','deleted') AND deleted_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_private_media_refs_subject
    ON private_media_refs(subject_hash,state,expires_at);
CREATE INDEX IF NOT EXISTS idx_private_media_refs_lifecycle
    ON private_media_refs(state,expires_at,purpose);

CREATE TABLE IF NOT EXISTS ai_operation_media_refs (
    operation_id        TEXT NOT NULL
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    media_ref_id        TEXT NOT NULL
                        REFERENCES private_media_refs(id) ON DELETE RESTRICT,
    ordinal             INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 9),
    created_at          TEXT NOT NULL,
    PRIMARY KEY(operation_id,media_ref_id),
    UNIQUE(operation_id,ordinal)
);
CREATE INDEX IF NOT EXISTS idx_ai_operation_media_refs_media
    ON ai_operation_media_refs(media_ref_id,operation_id);
CREATE TRIGGER IF NOT EXISTS noteai_operation_media_owner_guard_v1
BEFORE INSERT ON ai_operation_media_refs
WHEN NOT EXISTS (
    SELECT 1
    FROM ai_operations o
    JOIN private_media_refs m ON m.id=NEW.media_ref_id
    WHERE o.id=NEW.operation_id
      AND o.subject_hash=m.subject_hash
      AND m.state='ready'
      AND m.ready_at<=NEW.created_at
      AND m.expires_at>NEW.created_at
)
BEGIN
    SELECT RAISE(ABORT,'invalid owner-bound media link');
END;

CREATE TABLE IF NOT EXISTS ai_operation_outbox (
    id                  TEXT NOT NULL PRIMARY KEY CHECK (
                            length(id) = 36
                            AND length(replace(id, '-', '')) = 32
                            AND substr(id, 9, 1) = '-'
                            AND substr(id, 14, 1) = '-'
                            AND substr(id, 19, 1) = '-'
                            AND substr(id, 24, 1) = '-'
                            AND id NOT GLOB '*[^0-9a-f-]*'
                        ),
    operation_id        TEXT NOT NULL UNIQUE
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    event_type          TEXT NOT NULL CHECK (event_type = 'operation_ready'),
    state               TEXT NOT NULL CHECK (state IN ('pending','delivered','dead')),
    available_at        TEXT NOT NULL,
    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 20),
    lease_owner_hash    TEXT CHECK (
                            lease_owner_hash IS NULL OR (
                                length(lease_owner_hash) = 64
                                AND lease_owner_hash NOT GLOB '*[^0-9a-f]*'
                            )
                        ),
    lease_fence         INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
    lease_expires_at    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    delivered_at        TEXT,
    CHECK (
        (state = 'pending' AND delivered_at IS NULL)
        OR (state = 'delivered' AND delivered_at IS NOT NULL)
        OR state = 'dead'
    )
);
CREATE INDEX IF NOT EXISTS idx_ai_operation_outbox_dispatch
    ON ai_operation_outbox(state, available_at, lease_expires_at, created_at);

CREATE TABLE IF NOT EXISTS ai_operation_settlements (
    operation_id        TEXT NOT NULL PRIMARY KEY
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    request_ref_id      TEXT NOT NULL UNIQUE
                        REFERENCES ai_payload_refs(id) ON DELETE RESTRICT,
    result_ref_id       TEXT UNIQUE
                        REFERENCES ai_payload_refs(id) ON DELETE RESTRICT,
    billing_state       TEXT NOT NULL
                        CHECK (billing_state IN ('charged','completed','refunded','needs_manual')),
    failure_code        TEXT NOT NULL DEFAULT ''
                        CHECK (failure_code IN (
                            '', 'worker_failed', 'provider_failed',
                            'payload_unavailable', 'cancelled',
                            'provider_outcome_unknown', 'result_store_unknown'
                        )),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    settled_at          TEXT,
    CHECK (
        (billing_state = 'charged' AND settled_at IS NULL AND result_ref_id IS NULL)
        OR (
            billing_state = 'completed'
            AND settled_at IS NOT NULL
            AND result_ref_id IS NOT NULL
            AND failure_code = ''
        )
        OR (
            billing_state IN ('refunded','needs_manual')
            AND settled_at IS NOT NULL
            AND result_ref_id IS NULL
            AND failure_code <> ''
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_ai_operation_settlements_state
    ON ai_operation_settlements(billing_state, updated_at);

CREATE TABLE IF NOT EXISTS ai_dispatch_state (
    service_key         TEXT NOT NULL PRIMARY KEY CHECK (service_key = 'durable_ai'),
    priority_streak     INTEGER NOT NULL DEFAULT 0 CHECK (priority_streak BETWEEN 0 AND 3),
    updated_at          TEXT NOT NULL
);
INSERT INTO ai_dispatch_state(service_key,priority_streak,updated_at)
VALUES('durable_ai',0,'1970-01-01T00:00:00+00:00')
ON CONFLICT(service_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS saved_diagnoses (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    note_title      TEXT DEFAULT '',
    domain          TEXT DEFAULT '',
    ces_percentile  REAL,
    composite_score REAL,
    grade           TEXT DEFAULT '',
    diagnosis_json  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_saved_diag_user ON saved_diagnoses(user_id, created_at DESC);

-- ── 账户安全与验证挑战（不保存明文验证码/联系方式）───────────────
CREATE TABLE IF NOT EXISTS auth_login_limits (
    identifier_hash TEXT PRIMARY KEY,
    window_started_at TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    blocked_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_verification_challenges (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('phone','email')),
    destination_hash TEXT NOT NULL,
    destination_masked TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (
        purpose IN ('register_phone','bind_phone','verify_email','login_phone','password_reset')
    ),
    code_hash TEXT NOT NULL,
    code_salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
    requested_by_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    requester_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_verification_destination
    ON auth_verification_challenges(destination_hash,purpose,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_verification_expiry
    ON auth_verification_challenges(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_verification_requester
    ON auth_verification_challenges(requester_hash,purpose,created_at DESC)
    WHERE requester_hash <> '';

-- ── 首发归档合同元数据；内容本体仍在原业务表 ─────────────────────
CREATE TABLE IF NOT EXISTS content_retention (
    content_type TEXT NOT NULL CHECK (content_type IN ('note','diagnosis')),
    content_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    retention_class TEXT NOT NULL CHECK (retention_class IN ('free_7d','paid_indefinite')),
    active_until TEXT,
    recovery_until TEXT,
    deleted_at TEXT,
    purge_after TEXT,
    purged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    CONSTRAINT content_retention_state_check_h16 CHECK (
        (retention_class = 'paid_indefinite'
            AND active_until IS NULL
            AND recovery_until IS NULL
            AND (
                (deleted_at IS NULL
                    AND purge_after IS NULL
                    AND purged_at IS NULL)
                OR
                (deleted_at IS NOT NULL
                    AND purge_after IS NOT NULL
                    AND noteai_retention_clock_valid(deleted_at) = 1
                    AND noteai_retention_clock_valid(purge_after) = 1
                    AND noteai_retention_clock_lte(
                        deleted_at,purge_after
                    ) = 1
                    AND (
                        purged_at IS NULL
                        OR (
                            noteai_retention_clock_valid(purged_at) = 1
                            AND noteai_retention_clock_lte(
                                purge_after,purged_at
                            ) = 1
                        )
                    ))
            ))
        OR
        (retention_class = 'free_7d'
            AND active_until IS NOT NULL
            AND recovery_until IS NOT NULL
            AND purge_after IS NOT NULL
            AND noteai_retention_clock_valid(active_until) = 1
            AND noteai_retention_clock_valid(recovery_until) = 1
            AND noteai_retention_clock_valid(purge_after) = 1
            AND noteai_retention_clock_lte(
                active_until,recovery_until
            ) = 1
            AND noteai_retention_clock_lte(
                recovery_until,purge_after
            ) = 1
            AND (
                deleted_at IS NULL
                OR (
                    noteai_retention_clock_valid(deleted_at) = 1
                    AND noteai_retention_clock_lte(
                        deleted_at,purge_after
                    ) = 1
                )
            )
            AND (
                purged_at IS NULL
                OR (
                    noteai_retention_clock_valid(purged_at) = 1
                    AND noteai_retention_clock_lte(
                        purge_after,purged_at
                    ) = 1
                )
            ))
    ),
    PRIMARY KEY(content_type,content_id)
);
CREATE INDEX IF NOT EXISTS idx_content_retention_user_state
    ON content_retention(user_id,content_type,active_until,recovery_until);

CREATE TABLE IF NOT EXISTS account_deletion_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_ref TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    primary_inaccessible_at TEXT NOT NULL,
    primary_delete_by TEXT NOT NULL,
    backup_clear_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('requested','primary_deleted','backup_clear_pending','complete','cancelled')
    ),
    contract_version TEXT NOT NULL,
    primary_deleted_at TEXT,
    backup_cleared_at TEXT,
    backup_evidence_ref TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_account_deletion_open
    ON account_deletion_requests(user_id)
    WHERE status IN ('requested','primary_deleted','backup_clear_pending');

CREATE TABLE IF NOT EXISTS user_contract_acceptances (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contract_version TEXT NOT NULL,
    privacy_accepted_at TEXT NOT NULL,
    cross_border_notice_acknowledged_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('registration','account_settings')),
    PRIMARY KEY(user_id,contract_version)
);
CREATE INDEX IF NOT EXISTS idx_contract_acceptance_version
    ON user_contract_acceptances(contract_version,privacy_accepted_at);
        """)
        # 存量迁移：幂等加列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "nickname" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
        if "avatar_data" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_data TEXT")
        if "phone_verified_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN phone_verified_at TEXT")
        if "email_verified_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
        if "password_changed_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
        if "deletion_requested_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN deletion_requested_at TEXT")
        # subscriptions 表列名迁移：used_rewrite → used_chat_rewrite
        sub_cols = [r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()]
        if "used_rewrite" in sub_cols and "used_chat_rewrite" not in sub_cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN used_chat_rewrite INTEGER DEFAULT 0")
            conn.execute("UPDATE subscriptions SET used_chat_rewrite = used_rewrite")
        elif "used_chat_rewrite" not in sub_cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN used_chat_rewrite INTEGER DEFAULT 0")
        if "used_monthly_credits" not in sub_cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN used_monthly_credits REAL DEFAULT 0")
        usage_cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_records)").fetchall()]
        usage_additions = {
            "estimated_cost_rmb": "ALTER TABLE usage_records ADD COLUMN estimated_cost_rmb REAL DEFAULT 0",
            "actual_model_cost_rmb": "ALTER TABLE usage_records ADD COLUMN actual_model_cost_rmb REAL DEFAULT 0",
            "model_calls": "ALTER TABLE usage_records ADD COLUMN model_calls INTEGER DEFAULT 0",
            "model_names": "ALTER TABLE usage_records ADD COLUMN model_names TEXT DEFAULT ''",
            "cost_mode": "ALTER TABLE usage_records ADD COLUMN cost_mode TEXT DEFAULT 'estimated'",
        }
        for col, sql in usage_additions.items():
            if col not in usage_cols:
                conn.execute(sql)
        if "estimated_cost_rmb" not in usage_cols:
            conn.execute("UPDATE usage_records SET estimated_cost_rmb=COALESCE(cost_rmb,0) WHERE estimated_cost_rmb IS NULL OR estimated_cost_rmb=0")
        credit_txn_cols = [r[1] for r in conn.execute("PRAGMA table_info(credit_transactions)").fetchall()]
        credit_txn_additions = {
            "paid_rmb": "ALTER TABLE credit_transactions ADD COLUMN paid_rmb REAL DEFAULT 0",
            "package_id": "ALTER TABLE credit_transactions ADD COLUMN package_id TEXT DEFAULT ''",
            "payment_ref": "ALTER TABLE credit_transactions ADD COLUMN payment_ref TEXT DEFAULT ''",
        }
        for col, sql in credit_txn_additions.items():
            if col not in credit_txn_cols:
                conn.execute(sql)
        if "paid_rmb" not in credit_txn_cols:
            conn.execute(
                "UPDATE credit_transactions SET paid_rmb=amount*0.30 "
                "WHERE type='topup' AND (paid_rmb IS NULL OR paid_rmb=0)"
            )
        # phone / avatar_data 列幂等迁移
        user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "phone" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        if "avatar_data" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_data TEXT")
        phone_rows = conn.execute(
            "SELECT phone FROM users WHERE phone IS NOT NULL AND phone<>''"
        ).fetchall()
        if any(
            not re.fullmatch(r"\+861[3-9][0-9]{9}", str(row[0] or ""))
            for row in phone_rows
        ):
            raise RuntimeError(
                "non-canonical users.phone values block the unique index"
            )
        duplicate_phone = conn.execute(
            "SELECT phone FROM users WHERE phone IS NOT NULL AND phone<>'' "
            "GROUP BY phone HAVING COUNT(*)>1 LIMIT 1"
        ).fetchone()
        if duplicate_phone is not None:
            raise RuntimeError(
                "duplicate non-empty users.phone values block the unique index"
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique "
            "ON users(phone) WHERE phone IS NOT NULL AND phone<>''"
        )
        retention_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(content_retention)").fetchall()
        ]
        if "purged_at" not in retention_cols:
            conn.execute("ALTER TABLE content_retention ADD COLUMN purged_at TEXT")
        _upgrade_sqlite_content_retention_contract(conn)
        _ensure_sqlite_content_retention_purge_guards(conn)
        # Materialize every legacy archive before reads/purge jobs run. The
        # classification uses subscription coverage at content creation time,
        # matching PostgreSQL migration 0009.
        source_clock_rows = conn.execute(
            """
            SELECT value FROM (
                SELECT created_at AS value FROM notes
                UNION ALL
                SELECT created_at AS value FROM saved_diagnoses
                UNION ALL
                SELECT started_at AS value FROM subscriptions
                UNION ALL
                SELECT expires_at AS value FROM subscriptions
            ) source_clocks
            """
        )
        if any(
            not _valid_retention_source_clock(row["value"])
            for row in source_clock_rows
        ):
            raise RuntimeError(
                "invalid retention source clocks block startup"
            )
        paid_windows_by_user: dict[str, list[tuple[_datetime, _datetime]]] = {}
        for row in conn.execute(
            "SELECT user_id,tier,started_at,expires_at FROM subscriptions"
        ):
            if row["tier"] == "free":
                continue
            started_at = _parse_retention_source_clock(row["started_at"])
            expires_at = _parse_retention_source_clock(row["expires_at"])
            if started_at is None or expires_at is None:
                raise RuntimeError(
                    "invalid retention source clocks block startup"
                )
            paid_windows_by_user.setdefault(row["user_id"], []).append(
                (started_at, expires_at)
            )
        updated_at = _datetime.now(_timezone.utc).isoformat()
        for content_type, table in (
            ("note", "notes"),
            ("diagnosis", "saved_diagnoses"),
        ):
            for row in conn.execute(
                f"SELECT id,user_id,created_at FROM {table}"
            ).fetchall():
                created_at = _parse_retention_source_clock(row["created_at"])
                if created_at is None:
                    raise RuntimeError(
                        "invalid retention source clocks block startup"
                    )
                paid = any(
                    started_at <= created_at < expires_at
                    for started_at, expires_at in paid_windows_by_user.get(
                        row["user_id"],
                        (),
                    )
                )
                active_until = (
                    None
                    if paid
                    else (created_at + _timedelta(days=7)).isoformat()
                )
                recovery_until = (
                    None
                    if paid
                    else (created_at + _timedelta(days=14)).isoformat()
                )
                purge_after = (
                    None
                    if paid
                    else (created_at + _timedelta(days=44)).isoformat()
                )
                existing_retention = conn.execute(
                    "SELECT user_id,created_at,"
                    "contract_version FROM content_retention "
                    "WHERE content_type=? AND content_id=?",
                    (content_type, row["id"]),
                ).fetchone()
                if existing_retention is not None:
                    existing_created_at = _parse_retention_source_clock(
                        existing_retention["created_at"]
                    )
                    if (
                        existing_retention["user_id"] != row["user_id"]
                        or existing_created_at != created_at
                        or existing_retention["contract_version"]
                        != "first-launch-2026-07-25"
                    ):
                        raise RuntimeError(
                            "content retention identity mismatch blocks startup"
                        )
                    continue
                conn.execute(
                    """
                    INSERT INTO content_retention(
                        content_type,content_id,user_id,retention_class,
                        active_until,recovery_until,deleted_at,purge_after,
                        purged_at,created_at,updated_at,contract_version
                    ) VALUES(?,?,?,?,?,?,NULL,?,NULL,?,?,?)
                    """,
                    (
                        content_type,
                        row["id"],
                        row["user_id"],
                        "paid_indefinite" if paid else "free_7d",
                        active_until,
                        recovery_until,
                        purge_after,
                        created_at.isoformat(),
                        updated_at,
                        "first-launch-2026-07-25",
                    ),
                )
        memory_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(user_memories)").fetchall()
        ]
        if "source_note_id" not in memory_cols:
            conn.execute("ALTER TABLE user_memories ADD COLUMN source_note_id TEXT")
        retention_rows = conn.execute(
            "SELECT retention_class,active_until,recovery_until,deleted_at,"
            "purge_after,purged_at FROM content_retention"
        ).fetchall()
        if any(
            not _valid_content_retention_row(row)
            for row in retention_rows
        ):
            raise RuntimeError("invalid content retention clocks block startup")
        forged_purge = conn.execute(
            """
            SELECT 1
            FROM content_retention retention
            WHERE retention.purged_at IS NOT NULL
              AND (
                (
                    retention.content_type = 'note'
                    AND EXISTS (
                        SELECT 1 FROM notes
                        WHERE id = retention.content_id
                          AND user_id = retention.user_id
                    )
                )
                OR
                (
                    retention.content_type = 'diagnosis'
                    AND EXISTS (
                        SELECT 1 FROM saved_diagnoses
                        WHERE id = retention.content_id
                          AND user_id = retention.user_id
                    )
                )
              )
            LIMIT 1
            """
        ).fetchone()
        if forged_purge is not None:
            raise RuntimeError(
                "content purge marker without primary deletion blocks startup"
            )
        deletion_cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(account_deletion_requests)"
            ).fetchall()
        ]
        deletion_additions = {
            "subject_ref": (
                "ALTER TABLE account_deletion_requests "
                "ADD COLUMN subject_ref TEXT NOT NULL DEFAULT ''"
            ),
            "primary_deleted_at": (
                "ALTER TABLE account_deletion_requests "
                "ADD COLUMN primary_deleted_at TEXT"
            ),
            "backup_cleared_at": (
                "ALTER TABLE account_deletion_requests "
                "ADD COLUMN backup_cleared_at TEXT"
            ),
            "backup_evidence_ref": (
                "ALTER TABLE account_deletion_requests "
                "ADD COLUMN backup_evidence_ref TEXT"
            ),
        }
        for col, sql in deletion_additions.items():
            if col not in deletion_cols:
                conn.execute(sql)
        # tracked_notes 表（URL 追踪）
        conn.executescript("""
CREATE TABLE IF NOT EXISTS tracked_notes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_note_id  TEXT REFERENCES notes(id) ON DELETE SET NULL,          -- 被追踪的具体 note version
    source_root_note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,      -- 版本链根 note，便于聚合
    source_session_id TEXT REFERENCES chat_sessions(id) ON DELETE SET NULL,-- 生成/对话 session
    xhs_url         TEXT NOT NULL,
    xhs_note_id     TEXT,               -- 从 URL 解析出的小红书 note id
    note_title      TEXT,               -- 笔记标题（从主站获取或用户填写）
    domain          TEXT DEFAULT '美食',
    predicted_ces   REAL,               -- NoteAI 发布前的预测分
    published_at    TEXT,               -- 用户声明的发布时间
    submitted_at    TEXT NOT NULL,      -- 用户提交 URL 的时间
    -- 24h 首次采集
    check_24h_at    TEXT,
    likes_24h       INTEGER,
    saves_24h       INTEGER,
    comments_24h    INTEGER,
    -- 7天终态采集
    check_7d_at     TEXT,
    likes_7d        INTEGER,
    saves_7d        INTEGER,
    comments_7d     INTEGER,
    views_est       INTEGER,            -- 估算浏览量
    next_check_at   TEXT,               -- 下一次应采集时间（worker 使用）
    last_checked_at TEXT,               -- 最近一次采集尝试时间
    attempt_count   INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 2,
    -- 用户手动回填（当自动采集失败时）
    manual_filled   INTEGER DEFAULT 0,
    -- 计算结果
    actual_ces      REAL,               -- 真实 CES 分位（计算后写入）
    confidence      REAL,               -- 证据置信度 0-1
    confidence_label TEXT,              -- 高|中|低
    evidence_source TEXT DEFAULT '',    -- crawler|screenshot|manual|mixed
    training_eligible INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending',
    -- 'pending' | 'checking_24h' | 'checking_7d' | 'needs_manual' | 'complete' | 'failed'
    last_error_code TEXT,
    last_error      TEXT,
    completed_at    TEXT,
    insights_json   TEXT,               -- AI 洞察结果 JSON
    claim_token     TEXT,
    claim_expires_at TEXT,
    active_attempt_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracked_user ON tracked_notes(user_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_status ON tracked_notes(status, submitted_at);
        """)
        tracked_cols = [r[1] for r in conn.execute("PRAGMA table_info(tracked_notes)").fetchall()]
        tracked_additions = {
            "source_note_id": "ALTER TABLE tracked_notes ADD COLUMN source_note_id TEXT",
            "source_root_note_id": "ALTER TABLE tracked_notes ADD COLUMN source_root_note_id TEXT",
            "source_session_id": "ALTER TABLE tracked_notes ADD COLUMN source_session_id TEXT",
            "next_check_at": "ALTER TABLE tracked_notes ADD COLUMN next_check_at TEXT",
            "last_checked_at": "ALTER TABLE tracked_notes ADD COLUMN last_checked_at TEXT",
            "attempt_count": "ALTER TABLE tracked_notes ADD COLUMN attempt_count INTEGER DEFAULT 0",
            "max_attempts": "ALTER TABLE tracked_notes ADD COLUMN max_attempts INTEGER DEFAULT 2",
            "confidence": "ALTER TABLE tracked_notes ADD COLUMN confidence REAL",
            "confidence_label": "ALTER TABLE tracked_notes ADD COLUMN confidence_label TEXT",
            "evidence_source": "ALTER TABLE tracked_notes ADD COLUMN evidence_source TEXT DEFAULT ''",
            "training_eligible": "ALTER TABLE tracked_notes ADD COLUMN training_eligible INTEGER DEFAULT 0",
            "last_error_code": "ALTER TABLE tracked_notes ADD COLUMN last_error_code TEXT",
            "last_error": "ALTER TABLE tracked_notes ADD COLUMN last_error TEXT",
            "completed_at": "ALTER TABLE tracked_notes ADD COLUMN completed_at TEXT",
            "claim_token": "ALTER TABLE tracked_notes ADD COLUMN claim_token TEXT",
            "claim_expires_at": "ALTER TABLE tracked_notes ADD COLUMN claim_expires_at TEXT",
            "active_attempt_id": "ALTER TABLE tracked_notes ADD COLUMN active_attempt_id TEXT",
        }
        for col, sql in tracked_additions.items():
            if col not in tracked_cols:
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_source_note ON tracked_notes(user_id, source_note_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_next_check ON tracked_notes(status, next_check_at)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tracked_user_url "
            "ON tracked_notes(user_id,xhs_url)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tracked_user_note "
            "ON tracked_notes(user_id,xhs_note_id) WHERE xhs_note_id IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracked_claim "
            "ON tracked_notes(status,claim_expires_at,active_attempt_id,next_check_at)"
        )
        conn.executescript("""
CREATE TABLE IF NOT EXISTS tracking_provider_attempts (
    id              TEXT PRIMARY KEY,
    track_id        TEXT NOT NULL REFERENCES tracked_notes(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id           TEXT NOT NULL,
    stage           TEXT NOT NULL CHECK(stage IN ('24h','7d')),
    status          TEXT NOT NULL CHECK(status IN ('started','succeeded','failed')),
    admitted_at     TEXT NOT NULL,
    completed_at    TEXT,
    error_code      TEXT,
    UNIQUE(track_id,stage)
);
CREATE INDEX IF NOT EXISTS idx_tracking_attempt_user
ON tracking_provider_attempts(user_id,admitted_at DESC);
CREATE TRIGGER IF NOT EXISTS tracking_attempt_owner_insert
BEFORE INSERT ON tracking_provider_attempts
WHEN NOT EXISTS (
    SELECT 1 FROM tracked_notes
    WHERE id=NEW.track_id AND user_id=NEW.user_id
)
BEGIN
    SELECT RAISE(ABORT, 'tracking attempt owner mismatch');
END;
CREATE TRIGGER IF NOT EXISTS tracking_attempt_owner_update
BEFORE UPDATE OF track_id,user_id ON tracking_provider_attempts
WHEN NOT EXISTS (
    SELECT 1 FROM tracked_notes
    WHERE id=NEW.track_id AND user_id=NEW.user_id
)
BEGIN
    SELECT RAISE(ABORT, 'tracking attempt owner mismatch');
END;
CREATE TRIGGER IF NOT EXISTS tracked_active_attempt_insert
BEFORE INSERT ON tracked_notes
WHEN NEW.active_attempt_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM tracking_provider_attempts
    WHERE id=NEW.active_attempt_id
      AND track_id=NEW.id
      AND user_id=NEW.user_id
)
BEGIN
    SELECT RAISE(ABORT, 'tracking active attempt mismatch');
END;
CREATE TRIGGER IF NOT EXISTS tracked_active_attempt_update
BEFORE UPDATE OF active_attempt_id ON tracked_notes
WHEN NEW.active_attempt_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM tracking_provider_attempts
    WHERE id=NEW.active_attempt_id
      AND track_id=NEW.id
      AND user_id=NEW.user_id
)
BEGIN
    SELECT RAISE(ABORT, 'tracking active attempt mismatch');
END;
        """)
        attempt_cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(tracking_provider_attempts)"
            ).fetchall()
        ]
        if "run_id" not in attempt_cols:
            conn.execute(
                "ALTER TABLE tracking_provider_attempts "
                "ADD COLUMN run_id TEXT"
            )
            conn.execute(
                "UPDATE tracking_provider_attempts "
                "SET run_id='legacy-' || id WHERE run_id IS NULL"
            )
        conn.executescript("""
CREATE TABLE IF NOT EXISTS admin_sessions (
    token       TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS managed_prompts (
    key         TEXT PRIMARY KEY,
    label       TEXT DEFAULT '',
    module      TEXT DEFAULT '',
    content     TEXT NOT NULL,
    version     INTEGER DEFAULT 1,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_key  TEXT NOT NULL REFERENCES managed_prompts(key) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    saved_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_history_key ON prompt_history(prompt_key, version DESC);

CREATE TABLE IF NOT EXISTS system_settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    is_secret   INTEGER DEFAULT 0,
    updated_at  TEXT NOT NULL
);
        """)
# ─────────────────────────────────────────────────────────────
# 通用 CRUD helpers
# ─────────────────────────────────────────────────────────────

def _postgres_sql(sql: str) -> str:
    return sql.replace("?", "%s")


class Transaction:
    """One explicit transaction with backend-compatible placeholders."""

    def __init__(self, conn, postgres: bool):
        self.conn = conn
        self.postgres = postgres

    def execute(self, sql: str, params: tuple = ()):
        return self.conn.execute(_postgres_sql(sql) if self.postgres else sql, params)

    def fetchone(self, sql: str, params: tuple = ()):
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        return self.execute(sql, params).fetchall()


@contextmanager
def transaction(*, write: bool = False):
    """Open an explicit SQLite/PostgreSQL transaction.

    SQLite writers use BEGIN IMMEDIATE so balance checks and deductions cannot
    race. PostgreSQL callers still need row locks for shared balance rows.
    """
    postgres = using_postgres()
    conn = get_conn()
    try:
        conn.execute("BEGIN" if postgres or not write else "BEGIN IMMEDIATE")
        yield Transaction(conn, postgres)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_postgres_migrations() -> list[str]:
    if not using_postgres():
        return []
    if not _POSTGRES_MIGRATIONS_DIR.exists():
        raise RuntimeError(f"PostgreSQL migrations not found: {_POSTGRES_MIGRATIONS_DIR}")
    migration_paths = sorted(_POSTGRES_MIGRATIONS_DIR.glob("*.sql"))
    migration_payloads = {
        path.name: path.read_bytes()
        for path in migration_paths
    }
    migration_hashes = {
        version: hashlib.sha256(payload).hexdigest()
        for version, payload in migration_payloads.items()
    }
    applied: list[str] = []
    conn = _get_postgres_conn()
    try:
        with conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, sha256 TEXT, "
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.execute(
                "ALTER TABLE schema_migrations "
                "ADD COLUMN IF NOT EXISTS sha256 TEXT"
            )
            conn.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'schema_migrations'::regclass
                          AND conname = 'schema_migrations_sha256_format'
                    ) THEN
                        ALTER TABLE schema_migrations
                            ADD CONSTRAINT schema_migrations_sha256_format
                            CHECK (sha256 ~ '^[0-9a-f]{64}$');
                    END IF;
                END
                $$;
                """
            )
            rows = conn.execute(
                "SELECT version, sha256 FROM schema_migrations"
            ).fetchall()
            for row in rows:
                version = str(row["version"])
                actual_sha256 = migration_hashes.get(version)
                if actual_sha256 is None:
                    raise RuntimeError(
                        f"PostgreSQL migration missing locally: {version}"
                    )
                stored_sha256 = row["sha256"]
                if stored_sha256 is not None and str(stored_sha256) != actual_sha256:
                    raise RuntimeError(
                        f"PostgreSQL migration checksum mismatch: {version}"
                    )
                if stored_sha256 is None:
                    trusted_sha256 = _POSTGRES_LEGACY_MIGRATION_SHA256.get(version)
                    if trusted_sha256 != actual_sha256:
                        raise RuntimeError(
                            f"PostgreSQL migration checksum missing: {version}"
                        )
            for row in rows:
                if row["sha256"] is not None:
                    continue
                version = str(row["version"])
                conn.execute(
                    "UPDATE schema_migrations SET sha256=%s "
                    "WHERE version=%s AND sha256 IS NULL",
                    (migration_hashes[version], version),
                )
            conn.execute(
                "ALTER TABLE schema_migrations "
                "ALTER COLUMN sha256 SET NOT NULL"
            )
            existing = {str(row["version"]) for row in rows}
            for path in migration_paths:
                if path.name in existing:
                    continue
                conn.execute(migration_payloads[path.name].decode("utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(version,sha256) VALUES (%s,%s)",
                    (path.name, migration_hashes[path.name]),
                )
                applied.append(path.name)
    finally:
        conn.close()
    return applied


def init_db() -> None:
    """Initialize the backward-compatible local SQLite schema only.

    PostgreSQL schema changes are intentionally restricted to the explicit
    pre-deploy command, which calls ``apply_postgres_migrations`` directly.
    Importing an API process must never acquire schema-write authority.
    """
    if not using_postgres():
        _init_sqlite()


def database_health(
    *,
    connect_timeout_seconds: int = 1,
    query_timeout_ms: int = 1000,
) -> dict[str, Any]:
    """Run a fail-fast health probe without changing normal DB connections."""
    postgres = using_postgres()
    conn = (
        _get_postgres_conn(
            connect_timeout_seconds=connect_timeout_seconds,
            statement_timeout_ms=query_timeout_ms,
        )
        if postgres
        else _get_sqlite_conn(timeout_seconds=connect_timeout_seconds)
    )
    sqlite_deadline = time.monotonic() + max(0.1, query_timeout_ms / 1000)
    if not postgres:
        conn.set_progress_handler(
            lambda: 1 if time.monotonic() >= sqlite_deadline else 0,
            1,
        )
    try:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        ok = bool(row and (row["ok"] if isinstance(row, dict) else row["ok"]))
        return {"ok": ok, "backend": "postgresql" if postgres else "sqlite"}
    finally:
        if not postgres:
            try:
                conn.set_progress_handler(None, 0)
            finally:
                conn.close()
        else:
            conn.close()


def fetchone(sql: str, params: tuple = ()):
    conn = get_conn()
    try:
        return conn.execute(_postgres_sql(sql) if using_postgres() else sql, params).fetchone()
    finally:
        conn.close()


def fetchall(sql: str, params: tuple = ()) -> list:
    conn = get_conn()
    try:
        return conn.execute(_postgres_sql(sql) if using_postgres() else sql, params).fetchall()
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """返回 lastrowid。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(_postgres_sql(sql) if using_postgres() else sql, params)
            return int(getattr(cur, "lastrowid", 0) or 0)
    finally:
        conn.close()


def executemany(sql: str, params_list: list[tuple]) -> None:
    conn = get_conn()
    try:
        with conn:
            conn.executemany(_postgres_sql(sql) if using_postgres() else sql, params_list)
    finally:
        conn.close()


# Local SQLite keeps backward-compatible import-time initialization. PostgreSQL
# migrations run only through the explicit pre-deploy command.
if not using_postgres():
    init_db()
