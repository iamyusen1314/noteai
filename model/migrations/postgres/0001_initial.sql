CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT,
    avatar_emoji TEXT DEFAULT '🌸',
    nickname TEXT,
    phone TEXT,
    avatar_data TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    domain TEXT DEFAULT '美食',
    score DOUBLE PRECISION,
    grade TEXT,
    source TEXT DEFAULT 'generate',
    parent_id TEXT REFERENCES notes(id),
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    note_id TEXT REFERENCES notes(id),
    domain TEXT DEFAULT '美食',
    local_time TEXT,
    messages_json TEXT DEFAULT '[]',
    user_prefs_json TEXT DEFAULT '{}',
    iteration_count INTEGER DEFAULT 0,
    current_score DOUBLE PRECISION,
    generate_ctx_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_sessions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS user_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance DOUBLE PRECISION DEFAULT 0.5,
    decay_factor DOUBLE PRECISION DEFAULT 0.95,
    access_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_user ON user_memories(user_id, importance DESC);

CREATE TABLE IF NOT EXISTS growth_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_id TEXT REFERENCES notes(id),
    domain TEXT,
    score DOUBLE PRECISION NOT NULL,
    grade TEXT,
    action TEXT,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_growth_user ON growth_records(user_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier TEXT NOT NULL DEFAULT 'free',
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    used_analyze INTEGER DEFAULT 0,
    used_generate INTEGER DEFAULT 0,
    used_chat_rewrite INTEGER DEFAULT 0,
    used_screenshot INTEGER DEFAULT 0,
    used_monthly_credits DOUBLE PRECISION DEFAULT 0,
    period_start TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_rmb DOUBLE PRECISION DEFAULT 0,
    estimated_cost_rmb DOUBLE PRECISION DEFAULT 0,
    actual_model_cost_rmb DOUBLE PRECISION DEFAULT 0,
    model_calls INTEGER DEFAULT 0,
    model_names TEXT DEFAULT '',
    cost_mode TEXT DEFAULT 'estimated',
    credits_used DOUBLE PRECISION DEFAULT 0,
    source TEXT DEFAULT 'subscription',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(user_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    balance DOUBLE PRECISION DEFAULT 0,
    total_purchased DOUBLE PRECISION DEFAULT 0,
    total_used DOUBLE PRECISION DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    balance_after DOUBLE PRECISION NOT NULL,
    description TEXT,
    paid_rmb DOUBLE PRECISION DEFAULT 0,
    package_id TEXT DEFAULT '',
    payment_ref TEXT DEFAULT '',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ctxn_user ON credit_transactions(user_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS saved_diagnoses (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_title TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    ces_percentile DOUBLE PRECISION,
    composite_score DOUBLE PRECISION,
    grade TEXT DEFAULT '',
    diagnosis_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_saved_diag_user ON saved_diagnoses(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS tracked_notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    source_root_note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    source_session_id TEXT REFERENCES chat_sessions(id) ON DELETE SET NULL,
    xhs_url TEXT NOT NULL,
    xhs_note_id TEXT,
    note_title TEXT,
    domain TEXT DEFAULT '美食',
    predicted_ces DOUBLE PRECISION,
    published_at TEXT,
    submitted_at TEXT NOT NULL,
    check_24h_at TEXT,
    likes_24h INTEGER,
    saves_24h INTEGER,
    comments_24h INTEGER,
    check_7d_at TEXT,
    likes_7d INTEGER,
    saves_7d INTEGER,
    comments_7d INTEGER,
    views_est INTEGER,
    next_check_at TEXT,
    last_checked_at TEXT,
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 2,
    manual_filled INTEGER DEFAULT 0,
    actual_ces DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    confidence_label TEXT,
    evidence_source TEXT DEFAULT '',
    training_eligible INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    last_error_code TEXT,
    last_error TEXT,
    completed_at TEXT,
    insights_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracked_user ON tracked_notes(user_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_status ON tracked_notes(status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_tracked_source_note ON tracked_notes(user_id, source_note_id);
CREATE INDEX IF NOT EXISTS idx_tracked_next_check ON tracked_notes(status, next_check_at);
