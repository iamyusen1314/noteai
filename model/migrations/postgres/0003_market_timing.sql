CREATE TABLE IF NOT EXISTS hot_keywords (
    id BIGSERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    search_vol INTEGER DEFAULT 50,
    trend_dir INTEGER DEFAULT 0,
    source TEXT DEFAULT 'homefeed',
    category TEXT DEFAULT '',
    sample_count INTEGER DEFAULT 1,
    quality_score INTEGER DEFAULT 50,
    evidence_level TEXT DEFAULT 'weak',
    quality_reason TEXT DEFAULT '',
    captured_at TEXT NOT NULL,
    captured_date TEXT NOT NULL DEFAULT '',
    UNIQUE(keyword, category, captured_date)
);
CREATE INDEX IF NOT EXISTS idx_kw_captured ON hot_keywords(captured_at);
CREATE INDEX IF NOT EXISTS idx_kw_category_captured ON hot_keywords(category, captured_at);

CREATE TABLE IF NOT EXISTS keyword_snapshots (
    id BIGSERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    count INTEGER NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_kw ON keyword_snapshots(keyword, captured_at);

CREATE TABLE IF NOT EXISTS analysis_log (
    id BIGSERIAL PRIMARY KEY,
    note_hash TEXT NOT NULL UNIQUE,
    domain TEXT,
    analyzed_at TEXT NOT NULL,
    ces_percentile DOUBLE PRECISION,
    composite_score DOUBLE PRECISION,
    timing_coefficient DOUBLE PRECISION,
    keyword_search_vol DOUBLE PRECISION,
    trend_momentum DOUBLE PRECISION,
    is_trending_topic DOUBLE PRECISION,
    content_freshness DOUBLE PRECISION,
    category_saturation DOUBLE PRECISION,
    category_avg_ces DOUBLE PRECISION,
    keyword_competition DOUBLE PRECISION,
    trend_peak_distance DOUBLE PRECISION,
    matched_keywords TEXT,
    actual_ces_7d DOUBLE PRECISION DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS user_learn (
    user_id TEXT NOT NULL,
    pref_key TEXT NOT NULL,
    pref_value TEXT NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 0.5,
    update_count INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, pref_key)
);

CREATE TABLE IF NOT EXISTS crawler_events (
    id BIGSERIAL PRIMARY KEY,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crawler_events_created ON crawler_events(created_at DESC);
