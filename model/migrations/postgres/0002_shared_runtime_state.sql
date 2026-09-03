CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS managed_prompts (
    key TEXT PRIMARY KEY,
    label TEXT DEFAULT '',
    module TEXT DEFAULT '',
    content TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_history (
    id BIGSERIAL PRIMARY KEY,
    prompt_key TEXT NOT NULL REFERENCES managed_prompts(key) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    saved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_history_key ON prompt_history(prompt_key, version DESC);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    is_secret INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);
