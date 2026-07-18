CREATE TABLE IF NOT EXISTS ai_operations (
    id                     TEXT PRIMARY KEY
                           CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    subject_hash           TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    request_hash           TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
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
                               lease_owner_hash IS NULL
                               OR lease_owner_hash ~ '^[0-9a-f]{64}$'
                           ),
    lease_fence            INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
    lease_expires_at       TEXT,
    heartbeat_at           TEXT,
    claim_count            INTEGER NOT NULL DEFAULT 0 CHECK (claim_count >= 0),
    provider_attempt_count INTEGER NOT NULL DEFAULT 0
                           CHECK (provider_attempt_count >= 0),
    event_sequence         INTEGER NOT NULL DEFAULT 0 CHECK (event_sequence >= 0),
    result_hash            TEXT CHECK (
                               result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'
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
    id               TEXT PRIMARY KEY,
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
                         detail_hash IS NULL OR detail_hash ~ '^[0-9a-f]{64}$'
                     ),
    item_count       INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    recorded_at      TEXT NOT NULL,
    UNIQUE(operation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_ai_operation_events_replay
    ON ai_operation_events(operation_id, sequence);

CREATE TABLE IF NOT EXISTS ai_provider_attempts (
    id             TEXT PRIMARY KEY,
    operation_id   TEXT NOT NULL REFERENCES ai_operations(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    fence          INTEGER NOT NULL CHECK (fence > 0),
    provider       TEXT NOT NULL CHECK (provider IN ('claude', 'kimi')),
    state          TEXT NOT NULL
                   CHECK (state IN (
                       'provider_started', 'provider_succeeded',
                       'provider_failed', 'outcome_unknown'
                   )),
    request_hash   TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    model_hash     TEXT NOT NULL CHECK (model_hash ~ '^[0-9a-f]{64}$'),
    response_hash  TEXT CHECK (
                       response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'
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
