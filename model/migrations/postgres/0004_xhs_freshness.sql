CREATE TABLE IF NOT EXISTS xhs_crawler_health (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    domain TEXT DEFAULT '',
    profile_cookie_valid INTEGER DEFAULT 0,
    note_page_access_valid INTEGER DEFAULT 0,
    shortlink_canonicalized INTEGER DEFAULT 0,
    selector_valid INTEGER DEFAULT 0,
    risk_login_detected INTEGER DEFAULT 0,
    evidence_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_code TEXT DEFAULT '',
    error_summary TEXT DEFAULT '',
    checked_at TEXT NOT NULL,
    details_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_xhs_health_run ON xhs_crawler_health(run_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_xhs_health_domain ON xhs_crawler_health(domain, checked_at);

CREATE TABLE IF NOT EXISTS xhs_freshness_ledger (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    evidence_date TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    fresh_until TEXT NOT NULL,
    last_run_id TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    UNIQUE(domain, evidence_date)
);
CREATE INDEX IF NOT EXISTS idx_xhs_freshness_domain ON xhs_freshness_ledger(domain, acquired_at);
CREATE INDEX IF NOT EXISTS idx_xhs_freshness_status ON xhs_freshness_ledger(status, fresh_until);
