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
    credits_used         DOUBLE PRECISION DEFAULT 0,
    monthly_credits_used DOUBLE PRECISION DEFAULT 0,
    wallet_credits_used  DOUBLE PRECISION DEFAULT 0,
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
