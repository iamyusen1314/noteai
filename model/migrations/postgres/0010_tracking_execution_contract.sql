-- XHS Tracking: canonical identity, atomic claims and at-most-once provider admission.
-- This migration intentionally contains no role, GRANT, REVOKE or service change.

ALTER TABLE tracked_notes
    ADD COLUMN claim_token TEXT,
    ADD COLUMN claim_expires_at TEXT,
    ADD COLUMN active_attempt_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tracked_notes
        WHERE xhs_note_id IS NULL
           OR xhs_note_id !~ '^[0-9a-f]{24}$'
           OR xhs_url <>
              'https://www.xiaohongshu.com/explore/' || xhs_note_id
    ) THEN
        RAISE EXCEPTION
            'tracking migration blocked: noncanonical note identity';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM tracked_notes
        GROUP BY user_id, xhs_url
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'tracking migration blocked: duplicate stored URL identity';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM tracked_notes
        GROUP BY user_id, xhs_note_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'tracking migration blocked: duplicate note identity';
    END IF;
END
$$;

DO $$
DECLARE
    clock_pattern CONSTANT TEXT :=
        '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$';
BEGIN
    IF EXISTS (
        SELECT 1 FROM tracked_notes
        WHERE submitted_at IS NULL
           OR submitted_at !~ clock_pattern
           OR (published_at IS NOT NULL AND published_at !~ clock_pattern)
           OR (next_check_at IS NOT NULL AND next_check_at !~ clock_pattern)
           OR (check_24h_at IS NOT NULL AND check_24h_at !~ clock_pattern)
           OR (check_7d_at IS NOT NULL AND check_7d_at !~ clock_pattern)
           OR (last_checked_at IS NOT NULL AND last_checked_at !~ clock_pattern)
           OR (completed_at IS NOT NULL AND completed_at !~ clock_pattern)
    ) THEN
        RAISE EXCEPTION 'tracking migration blocked: invalid tracking clock';
    END IF;
END
$$;

DO $$
BEGIN
    PERFORM
        submitted_at::timestamptz,
        published_at::timestamptz,
        next_check_at::timestamptz,
        check_24h_at::timestamptz,
        check_7d_at::timestamptz,
        last_checked_at::timestamptz,
        completed_at::timestamptz
    FROM tracked_notes;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'tracking migration blocked: invalid tracking clock';
END
$$;

ALTER TABLE tracked_notes
    ALTER COLUMN xhs_note_id SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ADD CONSTRAINT tracked_notes_owner_identity UNIQUE(id, user_id);

CREATE UNIQUE INDEX uq_tracked_user_url
    ON tracked_notes(user_id, xhs_url);
CREATE UNIQUE INDEX uq_tracked_user_note
    ON tracked_notes(user_id, xhs_note_id);
CREATE INDEX idx_tracked_claim
    ON tracked_notes(
        status,
        claim_expires_at,
        active_attempt_id,
        next_check_at
    );

ALTER TABLE tracked_notes
    ADD CONSTRAINT tracked_notes_status_contract
    CHECK (
        status IS NOT NULL
        AND status IN (
            'pending',
            'checking_24h',
            'checking_7d',
            'needs_manual',
            'complete',
            'failed',
            'account_deletion_pending'
        )
    ),
    ADD CONSTRAINT tracked_notes_canonical_identity_contract
    CHECK (
        xhs_note_id ~ '^[0-9a-f]{24}$'
        AND xhs_url =
            'https://www.xiaohongshu.com/explore/' || xhs_note_id
    ),
    ADD CONSTRAINT tracked_notes_metric_contract
    CHECK (
        COALESCE(likes_24h, 0) >= 0
        AND COALESCE(likes_24h, 0) <= 2147483647
        AND COALESCE(saves_24h, 0) >= 0
        AND COALESCE(saves_24h, 0) <= 2147483647
        AND COALESCE(comments_24h, 0) >= 0
        AND COALESCE(comments_24h, 0) <= 2147483647
        AND COALESCE(likes_7d, 0) >= 0
        AND COALESCE(likes_7d, 0) <= 2147483647
        AND COALESCE(saves_7d, 0) >= 0
        AND COALESCE(saves_7d, 0) <= 2147483647
        AND COALESCE(comments_7d, 0) >= 0
        AND COALESCE(comments_7d, 0) <= 2147483647
        AND COALESCE(views_est, 0) >= 0
        AND COALESCE(views_est, 0) <= 2147483647
        AND attempt_count IS NOT NULL
        AND attempt_count BETWEEN 0 AND 2
        AND max_attempts IS NOT NULL
        AND max_attempts BETWEEN 1 AND 2
        AND manual_filled IS NOT NULL
        AND manual_filled IN (0, 1)
        AND training_eligible IS NOT NULL
        AND training_eligible IN (0, 1)
        AND (confidence IS NULL OR confidence BETWEEN 0 AND 1)
    ),
    ADD CONSTRAINT tracked_notes_claim_contract
    CHECK (
        (claim_token IS NULL AND claim_expires_at IS NULL)
        OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
    ),
    ADD CONSTRAINT tracked_notes_attempt_contract
    CHECK (active_attempt_id IS NULL OR claim_token IS NOT NULL),
    ADD CONSTRAINT tracked_notes_completion_contract
    CHECK (
        status <> 'complete'
        OR (
            completed_at IS NOT NULL
            AND check_7d_at IS NOT NULL
            AND likes_7d IS NOT NULL
            AND saves_7d IS NOT NULL
            AND comments_7d IS NOT NULL
            AND actual_ces IS NOT NULL
        )
    ),
    ADD CONSTRAINT tracked_notes_clock_contract
    CHECK (
        submitted_at ~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
        AND submitted_at::timestamptz IS NOT NULL
        AND (
            published_at IS NULL
            OR (
                published_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND published_at::timestamptz IS NOT NULL
            )
        )
        AND (
            next_check_at IS NULL
            OR (
                next_check_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND next_check_at::timestamptz IS NOT NULL
            )
        )
        AND (
            check_24h_at IS NULL
            OR (
                check_24h_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND check_24h_at::timestamptz IS NOT NULL
            )
        )
        AND (
            check_7d_at IS NULL
            OR (
                check_7d_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND check_7d_at::timestamptz IS NOT NULL
            )
        )
        AND (
            claim_expires_at IS NULL
            OR (
                claim_expires_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND claim_expires_at::timestamptz IS NOT NULL
            )
        )
        AND (
            last_checked_at IS NULL
            OR (
                last_checked_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND last_checked_at::timestamptz IS NOT NULL
            )
        )
        AND (
            completed_at IS NULL
            OR (
                completed_at ~
                    '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
                AND completed_at::timestamptz IS NOT NULL
            )
        )
        AND (
            check_24h_at IS NULL
            OR check_7d_at IS NULL
            OR check_24h_at::timestamptz <= check_7d_at::timestamptz
        )
    );

CREATE TABLE tracking_provider_attempts (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('24h', '7d')),
    status TEXT NOT NULL CHECK(status IN ('started', 'succeeded', 'failed')),
    admitted_at TEXT NOT NULL CHECK(
        admitted_at ~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
        AND admitted_at::timestamptz IS NOT NULL
    ),
    completed_at TEXT CHECK(
        completed_at IS NULL
        OR (
            completed_at ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$'
            AND completed_at::timestamptz IS NOT NULL
        )
    ),
    error_code TEXT,
    CONSTRAINT tracking_provider_attempt_owner_fk
        FOREIGN KEY(track_id, user_id)
        REFERENCES tracked_notes(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT tracking_provider_attempt_one_per_stage
        UNIQUE(track_id, stage),
    CONSTRAINT tracking_provider_attempt_active_identity
        UNIQUE(track_id, id),
    CONSTRAINT tracking_provider_attempt_completion
        CHECK (
            (status = 'started' AND completed_at IS NULL)
            OR (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
        )
);

CREATE INDEX idx_tracking_attempt_user
    ON tracking_provider_attempts(user_id, admitted_at DESC);

ALTER TABLE tracked_notes
    ADD CONSTRAINT tracked_notes_active_attempt_fk
    FOREIGN KEY(id, active_attempt_id)
    REFERENCES tracking_provider_attempts(track_id, id)
    DEFERRABLE INITIALLY DEFERRED;
