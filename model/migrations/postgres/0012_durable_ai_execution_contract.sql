SET LOCAL TIME ZONE 'UTC';

-- Repository contract only. Runtime roles receive no privileges here.
-- Raw prompts, request/result bodies, media, object keys, URLs, credentials,
-- provider envelopes and exception text are intentionally absent.

CREATE TABLE IF NOT EXISTS ai_payload_refs (
    id                  TEXT PRIMARY KEY
                        CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    operation_id        TEXT NOT NULL
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    subject_hash        TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    purpose             TEXT NOT NULL CHECK (purpose IN ('request','result')),
    object_key_hash     TEXT NOT NULL CHECK (object_key_hash ~ '^[0-9a-f]{64}$'),
    content_sha256      TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes          BIGINT NOT NULL CHECK (size_bytes BETWEEN 1 AND 134217728),
    item_count          INTEGER NOT NULL CHECK (item_count BETWEEN 0 AND 1000),
    schema_version      INTEGER NOT NULL CHECK (schema_version BETWEEN 1 AND 16),
    encryption_mode     TEXT NOT NULL CHECK (encryption_mode IN ('provider_managed','envelope_aes256')),
    key_epoch_hash      TEXT NOT NULL CHECK (key_epoch_hash ~ '^[0-9a-f]{64}$'),
    state               TEXT NOT NULL CHECK (state IN ('ready','expired','deleted')),
    expires_at          TEXT NOT NULL CHECK (
                            expires_at = btrim(expires_at)
                            AND expires_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND expires_at::timestamptz IS NOT NULL
                        ),
    created_at          TEXT NOT NULL CHECK (
                            created_at = btrim(created_at)
                            AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND created_at::timestamptz IS NOT NULL
                        ),
    ready_at            TEXT NOT NULL CHECK (
                            ready_at = btrim(ready_at)
                            AND ready_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND ready_at::timestamptz IS NOT NULL
                        ),
    deleted_at          TEXT,
    UNIQUE(operation_id, purpose),
    CHECK (created_at::timestamptz <= ready_at::timestamptz),
    CHECK (ready_at::timestamptz < expires_at::timestamptz),
    CHECK (
        (state = 'ready' AND deleted_at IS NULL)
        OR (
            state IN ('expired','deleted')
            AND deleted_at IS NOT NULL
            AND deleted_at = btrim(deleted_at)
            AND deleted_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
            AND deleted_at::timestamptz >= ready_at::timestamptz
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_ai_payload_refs_lifecycle
    ON ai_payload_refs(state, expires_at, purpose);
CREATE INDEX IF NOT EXISTS idx_ai_payload_refs_subject
    ON ai_payload_refs(subject_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_operation_outbox (
    id                  TEXT PRIMARY KEY
                        CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    operation_id        TEXT NOT NULL UNIQUE
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    event_type          TEXT NOT NULL CHECK (event_type = 'operation_ready'),
    state               TEXT NOT NULL CHECK (state IN ('pending','delivered','dead')),
    available_at        TEXT NOT NULL CHECK (
                            available_at = btrim(available_at)
                            AND available_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND available_at::timestamptz IS NOT NULL
                        ),
    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 20),
    lease_owner_hash    TEXT CHECK (
                            lease_owner_hash IS NULL OR lease_owner_hash ~ '^[0-9a-f]{64}$'
                        ),
    lease_fence         INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
    lease_expires_at    TEXT CHECK (
                            lease_expires_at IS NULL OR (
                                lease_expires_at = btrim(lease_expires_at)
                                AND lease_expires_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                                AND lease_expires_at::timestamptz IS NOT NULL
                            )
                        ),
    created_at          TEXT NOT NULL CHECK (
                            created_at = btrim(created_at)
                            AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND created_at::timestamptz IS NOT NULL
                        ),
    updated_at          TEXT NOT NULL CHECK (
                            updated_at = btrim(updated_at)
                            AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND updated_at::timestamptz IS NOT NULL
                        ),
    delivered_at        TEXT,
    CHECK (
        (state = 'pending' AND delivered_at IS NULL)
        OR (
            state = 'delivered'
            AND delivered_at IS NOT NULL
            AND delivered_at = btrim(delivered_at)
            AND delivered_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
            AND delivered_at::timestamptz IS NOT NULL
        )
        OR state = 'dead'
    ),
    CHECK (created_at::timestamptz <= updated_at::timestamptz)
);

CREATE INDEX IF NOT EXISTS idx_ai_operation_outbox_dispatch
    ON ai_operation_outbox(state, available_at, lease_expires_at, created_at);

CREATE TABLE IF NOT EXISTS ai_operation_settlements (
    operation_id        TEXT PRIMARY KEY
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
    created_at          TEXT NOT NULL CHECK (
                            created_at = btrim(created_at)
                            AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND created_at::timestamptz IS NOT NULL
                        ),
    updated_at          TEXT NOT NULL CHECK (
                            updated_at = btrim(updated_at)
                            AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND updated_at::timestamptz IS NOT NULL
                        ),
    settled_at          TEXT CHECK (
                            settled_at IS NULL OR (
                                settled_at = btrim(settled_at)
                                AND settled_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                                AND settled_at::timestamptz IS NOT NULL
                            )
                        ),
    CHECK (
        (billing_state = 'charged' AND settled_at IS NULL AND result_ref_id IS NULL)
        OR (
            billing_state = 'completed'
            AND settled_at IS NOT NULL
            AND settled_at::timestamptz IS NOT NULL
            AND result_ref_id IS NOT NULL
            AND failure_code = ''
        )
        OR (
            billing_state IN ('refunded','needs_manual')
            AND settled_at IS NOT NULL
            AND settled_at::timestamptz IS NOT NULL
            AND result_ref_id IS NULL
            AND failure_code <> ''
        )
    ),
    CHECK (created_at::timestamptz <= updated_at::timestamptz)
);

CREATE INDEX IF NOT EXISTS idx_ai_operation_settlements_state
    ON ai_operation_settlements(billing_state, updated_at);

CREATE TABLE IF NOT EXISTS ai_dispatch_state (
    service_key         TEXT PRIMARY KEY CHECK (service_key = 'durable_ai'),
    priority_streak     INTEGER NOT NULL DEFAULT 0 CHECK (priority_streak BETWEEN 0 AND 3),
    updated_at          TEXT NOT NULL CHECK (
                            updated_at = btrim(updated_at)
                            AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND updated_at::timestamptz IS NOT NULL
                        )
);

INSERT INTO ai_dispatch_state(service_key, priority_streak, updated_at)
VALUES ('durable_ai', 0, '1970-01-01T00:00:00+00:00')
ON CONFLICT(service_key) DO NOTHING;

ALTER TABLE ai_payload_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_operation_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_operation_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_dispatch_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS noteai_ai_payload_refs_select_v1 ON ai_payload_refs;
CREATE POLICY noteai_ai_payload_refs_select_v1 ON ai_payload_refs
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_app','noteai_ai_worker'));

DROP POLICY IF EXISTS noteai_ai_payload_refs_insert_v1 ON ai_payload_refs;
CREATE POLICY noteai_ai_payload_refs_insert_v1 ON ai_payload_refs
FOR INSERT TO PUBLIC
WITH CHECK (
    (current_user = 'noteai_app' AND purpose = 'request' AND state = 'ready')
    OR
    (current_user = 'noteai_ai_worker' AND purpose = 'result' AND state = 'ready')
);

DROP POLICY IF EXISTS noteai_ai_payload_refs_lifecycle_v1 ON ai_payload_refs;
CREATE POLICY noteai_ai_payload_refs_lifecycle_v1 ON ai_payload_refs
FOR UPDATE TO PUBLIC
USING (
    current_user IN ('noteai_app','noteai_ai_worker')
    AND state = 'ready'
)
WITH CHECK (
    current_user IN ('noteai_app','noteai_ai_worker')
    AND state IN ('expired','deleted')
    AND deleted_at IS NOT NULL
);

DROP POLICY IF EXISTS noteai_ai_outbox_api_insert_v1 ON ai_operation_outbox;
CREATE POLICY noteai_ai_outbox_api_insert_v1 ON ai_operation_outbox
FOR INSERT TO PUBLIC
WITH CHECK (
    current_user = 'noteai_app'
    AND event_type = 'operation_ready'
    AND state = 'pending'
    AND attempt_count = 0
    AND lease_owner_hash IS NULL
    AND lease_fence = 0
    AND lease_expires_at IS NULL
    AND delivered_at IS NULL
);

DROP POLICY IF EXISTS noteai_ai_outbox_api_cancel_v1 ON ai_operation_outbox;
CREATE POLICY noteai_ai_outbox_api_cancel_v1 ON ai_operation_outbox
FOR UPDATE TO PUBLIC
USING (
    current_user = 'noteai_app'
    AND state IN ('pending','delivered')
)
WITH CHECK (
    current_user = 'noteai_app'
    AND state = 'dead'
);

DROP POLICY IF EXISTS noteai_ai_outbox_dispatch_v1 ON ai_operation_outbox;
CREATE POLICY noteai_ai_outbox_dispatch_v1 ON ai_operation_outbox
FOR ALL TO PUBLIC
USING (current_user = 'noteai_ai_dispatcher')
WITH CHECK (current_user = 'noteai_ai_dispatcher');

DROP POLICY IF EXISTS noteai_ai_settlement_select_v1 ON ai_operation_settlements;
CREATE POLICY noteai_ai_settlement_select_v1 ON ai_operation_settlements
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_app','noteai_ai_worker'));

DROP POLICY IF EXISTS noteai_ai_settlement_api_insert_v1 ON ai_operation_settlements;
CREATE POLICY noteai_ai_settlement_api_insert_v1 ON ai_operation_settlements
FOR INSERT TO PUBLIC
WITH CHECK (
    current_user = 'noteai_app'
    AND billing_state = 'charged'
    AND failure_code = ''
    AND result_ref_id IS NULL
    AND settled_at IS NULL
);

DROP POLICY IF EXISTS noteai_ai_settlement_api_cancel_v1 ON ai_operation_settlements;
CREATE POLICY noteai_ai_settlement_api_cancel_v1 ON ai_operation_settlements
FOR UPDATE TO PUBLIC
USING (
    current_user = 'noteai_app'
    AND billing_state = 'charged'
)
WITH CHECK (
    current_user = 'noteai_app'
    AND billing_state = 'refunded'
    AND failure_code = 'cancelled'
    AND result_ref_id IS NULL
    AND settled_at IS NOT NULL
);

DROP POLICY IF EXISTS noteai_ai_settlement_worker_update_v1 ON ai_operation_settlements;
CREATE POLICY noteai_ai_settlement_worker_update_v1 ON ai_operation_settlements
FOR UPDATE TO PUBLIC
USING (
    current_user = 'noteai_ai_worker'
    AND billing_state = 'charged'
)
WITH CHECK (
    current_user = 'noteai_ai_worker'
    AND billing_state IN ('completed','refunded','needs_manual')
    AND settled_at IS NOT NULL
);

DROP POLICY IF EXISTS noteai_ai_dispatch_state_v1 ON ai_dispatch_state;
CREATE POLICY noteai_ai_dispatch_state_v1 ON ai_dispatch_state
FOR ALL TO PUBLIC
USING (current_user = 'noteai_ai_dispatcher')
WITH CHECK (
    current_user = 'noteai_ai_dispatcher'
    AND service_key = 'durable_ai'
    AND priority_streak BETWEEN 0 AND 3
);
