CREATE TABLE IF NOT EXISTS model_usage_records (
    id TEXT PRIMARY KEY,
    usage_record_id TEXT NOT NULL REFERENCES usage_records(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    unclassified_input_tokens INTEGER DEFAULT 0,
    cache_read_input_tokens INTEGER DEFAULT 0,
    cache_write_input_tokens INTEGER DEFAULT 0,
    cache_write_5m_tokens INTEGER DEFAULT 0,
    cache_write_1h_tokens INTEGER DEFAULT 0,
    cache_write_unknown_ttl_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    input_price_per_1m DOUBLE PRECISION,
    cache_read_price_per_1m DOUBLE PRECISION,
    cache_write_5m_price_per_1m DOUBLE PRECISION,
    cache_write_1h_price_per_1m DOUBLE PRECISION,
    output_price_per_1m DOUBLE PRECISION,
    price_currency TEXT NOT NULL,
    usd_cny DOUBLE PRECISION NOT NULL,
    price_version TEXT NOT NULL,
    known_cost_rmb DOUBLE PRECISION DEFAULT 0,
    pricing_status TEXT NOT NULL,
    usage_status TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_usage_parent
    ON model_usage_records(usage_record_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_model_usage_model
    ON model_usage_records(provider, model, recorded_at);
