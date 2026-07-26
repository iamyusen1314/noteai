CREATE TABLE xhs_trends_runs (
    id                     TEXT PRIMARY KEY,
    bucket_key             TEXT NOT NULL UNIQUE
                               CHECK (
                                   bucket_key ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                                   AND to_char(
                                       to_date(bucket_key, 'YYYY-MM-DD'),
                                       'YYYY-MM-DD'
                                   ) = bucket_key
                               ),
    status                 TEXT NOT NULL
                               CHECK (status IN (
                                   'running', 'succeeded', 'failed', 'needs_manual'
                               )),
    lease_token_hash       TEXT NOT NULL
                               CHECK (
                                   length(lease_token_hash) = 64
                                   AND lease_token_hash ~ '^[0-9a-f]{64}$'
                               ),
    lease_fence            BIGINT NOT NULL CHECK (lease_fence > 0),
    lease_expires_at       TIMESTAMPTZ NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL,
    completed_at           TIMESTAMPTZ,
    provider_attempt_count INTEGER NOT NULL DEFAULT 0
                               CHECK (
                                   provider_attempt_count BETWEEN 0 AND 34
                               ),
    last_error_code        TEXT NOT NULL DEFAULT ''
                               CHECK (length(last_error_code) <= 64),
    snapshot_sha256        TEXT NOT NULL DEFAULT ''
                               CHECK (
                                   snapshot_sha256 = ''
                                   OR (
                                       length(snapshot_sha256) = 64
                                       AND snapshot_sha256 ~ '^[0-9a-f]{64}$'
                                   )
                               ),
    snapshot_size          INTEGER NOT NULL DEFAULT 0
                               CHECK (snapshot_size BETWEEN 0 AND 1048576),
    CONSTRAINT xhs_trends_run_completion CHECK (
        (
            status = 'running'
            AND completed_at IS NULL
            AND lease_expires_at > started_at
        )
        OR (
            status <> 'running'
            AND completed_at IS NOT NULL
            AND completed_at >= started_at
            AND lease_expires_at > started_at
        )
    ),
    CONSTRAINT xhs_trends_run_snapshot_shape CHECK (
        (
            status = 'succeeded'
            AND length(snapshot_sha256) = 64
            AND snapshot_size > 0
        )
        OR (
            status <> 'succeeded'
            AND snapshot_sha256 = ''
            AND snapshot_size = 0
        )
    ),
    UNIQUE (id, lease_token_hash, lease_fence)
);

CREATE TABLE xhs_trends_service_state (
    service_key            TEXT PRIMARY KEY
                               CHECK (service_key = 'market_timing'),
    active_run_id          TEXT,
    status                 TEXT NOT NULL
                               CHECK (status IN ('idle', 'running', 'needs_manual')),
    lease_token_hash       TEXT,
    lease_fence            BIGINT NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
    lease_expires_at       TIMESTAMPTZ,
    session_blocked        BOOLEAN NOT NULL DEFAULT FALSE,
    session_block_reason   TEXT NOT NULL DEFAULT ''
                               CHECK (
                                   session_block_reason IN (
                                       '', 'server_session_logged_out'
                                   )
                               ),
    session_blocked_at     TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ NOT NULL,
    CONSTRAINT xhs_trends_state_active_fk
        FOREIGN KEY (active_run_id, lease_token_hash, lease_fence)
        REFERENCES xhs_trends_runs(id, lease_token_hash, lease_fence)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT xhs_trends_state_shape CHECK (
        (
            status = 'idle'
            AND active_run_id IS NULL
            AND lease_token_hash IS NULL
            AND lease_expires_at IS NULL
        )
        OR (
            status IN ('running', 'needs_manual')
            AND active_run_id IS NOT NULL
            AND lease_token_hash IS NOT NULL
            AND length(lease_token_hash) = 64
            AND lease_token_hash ~ '^[0-9a-f]{64}$'
            AND lease_fence > 0
            AND lease_expires_at IS NOT NULL
        )
    ),
    CONSTRAINT xhs_trends_session_block_shape CHECK (
        (
            session_blocked = FALSE
            AND session_block_reason = ''
            AND session_blocked_at IS NULL
        )
        OR (
            session_blocked = TRUE
            AND session_block_reason = 'server_session_logged_out'
            AND session_blocked_at IS NOT NULL
        )
    )
);

CREATE TABLE xhs_trends_provider_attempts (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES xhs_trends_runs(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 34),
    endpoint        TEXT NOT NULL
                        CHECK (endpoint IN (
                            'homefeed', 'search_recommend', 'search_notes'
                        )),
    status          TEXT NOT NULL
                        CHECK (status IN (
                            'admitted', 'succeeded', 'failed', 'outcome_unknown'
                        )),
    admitted_at     TIMESTAMPTZ NOT NULL,
    admitted_date   DATE NOT NULL,
    completed_at    TIMESTAMPTZ,
    error_code      TEXT NOT NULL DEFAULT ''
                        CHECK (length(error_code) <= 64),
    CONSTRAINT xhs_trends_attempt_one_per_ordinal UNIQUE (run_id, ordinal),
    CONSTRAINT xhs_trends_attempt_date CHECK (
        admitted_date = (admitted_at AT TIME ZONE 'UTC')::date
    ),
    CONSTRAINT xhs_trends_attempt_completion CHECK (
        (status = 'admitted' AND completed_at IS NULL)
        OR (
            status <> 'admitted'
            AND completed_at IS NOT NULL
            AND completed_at >= admitted_at
        )
    )
);

CREATE INDEX idx_xhs_trends_attempt_date
    ON xhs_trends_provider_attempts(admitted_date, admitted_at);
CREATE INDEX idx_xhs_trends_attempt_status
    ON xhs_trends_provider_attempts(status, admitted_at);

CREATE TABLE xhs_trends_snapshot_evidence (
    run_id             TEXT PRIMARY KEY
                            REFERENCES xhs_trends_runs(id) ON DELETE RESTRICT,
    schema_version     INTEGER NOT NULL CHECK (schema_version = 1),
    snapshot_sha256    TEXT NOT NULL
                            CHECK (
                                length(snapshot_sha256) = 64
                                AND snapshot_sha256 ~ '^[0-9a-f]{64}$'
                            ),
    snapshot_size      INTEGER NOT NULL
                            CHECK (snapshot_size BETWEEN 1 AND 1048576),
    keyword_count      INTEGER NOT NULL
                            CHECK (keyword_count BETWEEN 72 AND 90),
    domain_counts_json JSONB NOT NULL
                            CHECK (
                                jsonb_typeof(domain_counts_json) = 'object'
                                AND domain_counts_json ?& ARRAY[
                                    '美食','旅行','穿搭','美妆','家居','健身'
                                ]
                                AND (
                                    domain_counts_json - ARRAY[
                                        '美食','旅行','穿搭','美妆','家居','健身'
                                    ]::TEXT[]
                                ) = '{}'::JSONB
                                AND jsonb_typeof(domain_counts_json->'美食') = 'number'
                                AND jsonb_typeof(domain_counts_json->'旅行') = 'number'
                                AND jsonb_typeof(domain_counts_json->'穿搭') = 'number'
                                AND jsonb_typeof(domain_counts_json->'美妆') = 'number'
                                AND jsonb_typeof(domain_counts_json->'家居') = 'number'
                                AND jsonb_typeof(domain_counts_json->'健身') = 'number'
                                AND (domain_counts_json->>'美食')::integer BETWEEN 12 AND 15
                                AND (domain_counts_json->>'旅行')::integer BETWEEN 12 AND 15
                                AND (domain_counts_json->>'穿搭')::integer BETWEEN 12 AND 15
                                AND (domain_counts_json->>'美妆')::integer BETWEEN 12 AND 15
                                AND (domain_counts_json->>'家居')::integer BETWEEN 12 AND 15
                                AND (domain_counts_json->>'健身')::integer BETWEEN 12 AND 15
                            ),
    payload_json       TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    CHECK (
        octet_length(convert_to(payload_json, 'UTF8')) = snapshot_size
        AND jsonb_typeof(payload_json::jsonb) = 'object'
        AND (payload_json::jsonb->>'schema_version')::integer = 1
        AND jsonb_typeof(payload_json::jsonb->'domains') = 'object'
        AND (payload_json::jsonb->'domains') ?& ARRAY[
            '美食','旅行','穿搭','美妆','家居','健身'
        ]
        AND (
            (payload_json::jsonb->'domains') - ARRAY[
                '美食','旅行','穿搭','美妆','家居','健身'
            ]::TEXT[]
        ) = '{}'::JSONB
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'美食'->'keywords'
        ) = (domain_counts_json->>'美食')::integer
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'旅行'->'keywords'
        ) = (domain_counts_json->>'旅行')::integer
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'穿搭'->'keywords'
        ) = (domain_counts_json->>'穿搭')::integer
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'美妆'->'keywords'
        ) = (domain_counts_json->>'美妆')::integer
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'家居'->'keywords'
        ) = (domain_counts_json->>'家居')::integer
        AND jsonb_array_length(
            payload_json::jsonb->'domains'->'健身'->'keywords'
        ) = (domain_counts_json->>'健身')::integer
    ),
    CHECK (
        keyword_count =
            (domain_counts_json->>'美食')::integer
            + (domain_counts_json->>'旅行')::integer
            + (domain_counts_json->>'穿搭')::integer
            + (domain_counts_json->>'美妆')::integer
            + (domain_counts_json->>'家居')::integer
            + (domain_counts_json->>'健身')::integer
    )
);

INSERT INTO xhs_trends_service_state(
    service_key,status,lease_fence,session_blocked,
    session_block_reason,updated_at
) VALUES (
    'market_timing','idle',0,FALSE,'',CURRENT_TIMESTAMP
);

-- Runtime privilege statements are intentionally absent. A separately
-- reviewed production task must create and verify the dedicated role.
