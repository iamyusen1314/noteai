-- Bounded, non-content retrieval observations on the original charged task.
-- Model accounting, payment records and historical usage amounts are unchanged.
ALTER TABLE usage_records ADD COLUMN fact_observations_json TEXT NOT NULL DEFAULT '[]'
    CHECK (octet_length(fact_observations_json) <= 65536
           AND jsonb_typeof(fact_observations_json::jsonb) = 'array');
