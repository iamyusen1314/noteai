"""NoteAI primary data access for local SQLite and cloud PostgreSQL."""
import sqlite3
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_DB_PATH = Path(
    os.environ.get("NOTEAI_SQLITE_PATH")
    or (Path(__file__).parent / "data" / "noteai.db")
)
_POSTGRES_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "postgres"


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
    connect_kwargs: dict[str, Any] = {"row_factory": _compat_row_factory}
    if connect_timeout_seconds is not None:
        connect_kwargs["connect_timeout"] = max(1, int(connect_timeout_seconds))
    if statement_timeout_ms is not None:
        timeout_ms = max(100, int(statement_timeout_ms))
        connect_kwargs["options"] = f"-c statement_timeout={timeout_ms}"
    return psycopg.connect(_database_url(), **connect_kwargs)


def get_conn():
    return _get_postgres_conn() if using_postgres() else _get_sqlite_conn()


def _init_sqlite() -> None:
    """创建所有表（幂等）。"""
    conn = _get_sqlite_conn()
    with conn:
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
    avatar_data  TEXT                       -- 上传的头像 base64
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
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_user ON user_memories(user_id, importance DESC);

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
        """)
        # 存量迁移：幂等加列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "nickname" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
        if "avatar_data" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_data TEXT")
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
    insights_json   TEXT                -- AI 洞察结果 JSON
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
        }
        for col, sql in tracked_additions.items():
            if col not in tracked_cols:
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_source_note ON tracked_notes(user_id, source_note_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_next_check ON tracked_notes(status, next_check_at)")
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
    conn.close()


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
    applied: list[str] = []
    conn = _get_postgres_conn()
    try:
        with conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
            existing = {str(row["version"]) for row in rows}
            for path in sorted(_POSTGRES_MIGRATIONS_DIR.glob("*.sql")):
                if path.name in existing:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (path.name,))
                applied.append(path.name)
    finally:
        conn.close()
    return applied


def init_db() -> None:
    if using_postgres():
        apply_postgres_migrations()
    else:
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
