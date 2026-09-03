SET LOCAL TIME ZONE 'UTC';

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified_at TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_requested_at TEXT;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_note_id TEXT
    REFERENCES notes(id) ON DELETE CASCADE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM users
        WHERE phone IS NOT NULL AND phone <> ''
          AND phone !~ '^\+861[3-9][0-9]{9}$'
    ) THEN
        RAISE EXCEPTION 'non-canonical users.phone values block the unique index';
    END IF;
    IF EXISTS (
        SELECT 1 FROM users
        WHERE phone IS NOT NULL AND phone <> ''
        GROUP BY phone HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'duplicate non-empty users.phone values block the unique index';
    END IF;
END
$$;

ALTER TABLE users
    ADD CONSTRAINT users_phone_canonical_check
    CHECK (phone IS NULL OR phone = '' OR phone ~ '^\+861[3-9][0-9]{9}$');

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique
    ON users(phone) WHERE phone IS NOT NULL AND phone <> '';

CREATE TABLE IF NOT EXISTS auth_login_limits (
    identifier_hash TEXT PRIMARY KEY,
    window_started_at TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    blocked_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_verification_challenges (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('phone','email')),
    destination_hash TEXT NOT NULL,
    destination_masked TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (
        purpose IN ('register_phone','bind_phone','verify_email','login_phone','password_reset')
    ),
    code_hash TEXT NOT NULL,
    code_salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
    requested_by_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    requester_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_verification_destination
    ON auth_verification_challenges(destination_hash,purpose,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_verification_expiry
    ON auth_verification_challenges(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_verification_requester
    ON auth_verification_challenges(requester_hash,purpose,created_at DESC)
    WHERE requester_hash <> '';

DO $$
DECLARE
    source_clock TEXT;
    normalized_clock TEXT;
    offset_parts TEXT[];
BEGIN
    FOR source_clock IN
        SELECT created_at AS source_clock FROM notes
        UNION ALL
        SELECT created_at AS source_clock FROM saved_diagnoses
        UNION ALL
        SELECT started_at AS source_clock FROM subscriptions
        UNION ALL
        SELECT expires_at AS source_clock FROM subscriptions
    LOOP
        normalized_clock := btrim(source_clock);
        IF normalized_clock IS NULL OR normalized_clock !~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
            '([01][0-9]|2[0-3]):[0-5][0-9]'
            '(:[0-5][0-9](\.[0-9]{1,6})?)?'
            '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))?$'
        THEN
            RAISE EXCEPTION 'invalid retention source clocks block migration';
        END IF;

        offset_parts := regexp_match(
            normalized_clock,
            '([+-])([0-9]{2})(:?([0-9]{2}))?$'
        );
        IF offset_parts IS NOT NULL AND (
            offset_parts[2]::INTEGER > 14
            OR COALESCE(offset_parts[4]::INTEGER, 0) > 59
            OR (
                offset_parts[2]::INTEGER = 14
                AND COALESCE(offset_parts[4]::INTEGER, 0) > 0
            )
        ) THEN
            RAISE EXCEPTION 'invalid retention source clocks block migration';
        END IF;

        BEGIN
            PERFORM btrim(source_clock)::timestamptz;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'invalid retention source clocks block migration';
        END;
    END LOOP;
END
$$;

CREATE TABLE IF NOT EXISTS content_retention (
    content_type TEXT NOT NULL CHECK (content_type IN ('note','diagnosis')),
    content_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    retention_class TEXT NOT NULL CHECK (retention_class IN ('free_7d','paid_indefinite')),
    active_until TEXT,
    recovery_until TEXT,
    deleted_at TEXT,
    purge_after TEXT,
    purged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    CONSTRAINT content_retention_clock_order_check CHECK (
        (retention_class = 'paid_indefinite'
            AND active_until IS NULL
            AND recovery_until IS NULL
            AND (
                (deleted_at IS NULL
                    AND purge_after IS NULL
                    AND purged_at IS NULL)
                OR
                (deleted_at IS NOT NULL
                    AND purge_after IS NOT NULL
                    AND deleted_at = btrim(deleted_at)
                    AND purge_after = btrim(purge_after)
                    AND btrim(deleted_at) ~
                        '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                        '([01][0-9]|2[0-3]):[0-5][0-9]'
                        '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                        '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
                    AND btrim(purge_after) ~
                        '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                        '([01][0-9]|2[0-3]):[0-5][0-9]'
                        '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                        '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
                    AND btrim(deleted_at)::timestamptz <= btrim(purge_after)::timestamptz
                    AND (
                        purged_at IS NULL
                        OR (
                            purged_at = btrim(purged_at)
                            AND btrim(purged_at) ~
                                '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                                '([01][0-9]|2[0-3]):[0-5][0-9]'
                                '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                                '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
                            AND btrim(purge_after)::timestamptz <= btrim(purged_at)::timestamptz
                        )
                    ))
            ))
        OR
        (retention_class = 'free_7d'
            AND active_until IS NOT NULL
            AND recovery_until IS NOT NULL
            AND purge_after IS NOT NULL
            AND active_until = btrim(active_until)
            AND recovery_until = btrim(recovery_until)
            AND purge_after = btrim(purge_after)
            AND btrim(active_until) ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                '([01][0-9]|2[0-3]):[0-5][0-9]'
                '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
            AND btrim(recovery_until) ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                '([01][0-9]|2[0-3]):[0-5][0-9]'
                '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
            AND btrim(purge_after) ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                '([01][0-9]|2[0-3]):[0-5][0-9]'
                '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
            AND btrim(active_until)::timestamptz <= btrim(recovery_until)::timestamptz
            AND btrim(recovery_until)::timestamptz <= btrim(purge_after)::timestamptz
            AND (
                deleted_at IS NULL
                OR (
                    deleted_at = btrim(deleted_at)
                    AND btrim(deleted_at) ~
                        '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                        '([01][0-9]|2[0-3]):[0-5][0-9]'
                        '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                        '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
                    AND btrim(deleted_at)::timestamptz <= btrim(purge_after)::timestamptz
                )
            )
            AND (
                purged_at IS NULL
                OR (
                    purged_at = btrim(purged_at)
                    AND btrim(purged_at) ~
                        '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                        '([01][0-9]|2[0-3]):[0-5][0-9]'
                        '(:[0-5][0-9](\.[0-9]{1,6})?)?'
                        '(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))$'
                    AND btrim(purge_after)::timestamptz <= btrim(purged_at)::timestamptz
                )
            ))
    ),
    PRIMARY KEY(content_type,content_id)
);
CREATE INDEX IF NOT EXISTS idx_content_retention_user_state
    ON content_retention(user_id,content_type,active_until,recovery_until);

INSERT INTO content_retention(
    content_type,content_id,user_id,retention_class,active_until,recovery_until,
    deleted_at,purge_after,purged_at,created_at,updated_at,contract_version
)
SELECT
    'note',n.id,n.user_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=n.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=n.created_at::timestamptz
          AND s.expires_at::timestamptz>n.created_at::timestamptz
    ) THEN 'paid_indefinite' ELSE 'free_7d' END,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=n.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=n.created_at::timestamptz
          AND s.expires_at::timestamptz>n.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        n.created_at::timestamptz + INTERVAL '7 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=n.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=n.created_at::timestamptz
          AND s.expires_at::timestamptz>n.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        n.created_at::timestamptz + INTERVAL '14 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    NULL,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=n.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=n.created_at::timestamptz
          AND s.expires_at::timestamptz>n.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        n.created_at::timestamptz + INTERVAL '44 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    NULL,n.created_at,to_char(NOW(),'YYYY-MM-DD"T"HH24:MI:SS.USOF'),
    'first-launch-2026-07-25'
FROM notes n
ON CONFLICT(content_type,content_id) DO NOTHING;

INSERT INTO content_retention(
    content_type,content_id,user_id,retention_class,active_until,recovery_until,
    deleted_at,purge_after,purged_at,created_at,updated_at,contract_version
)
SELECT
    'diagnosis',d.id,d.user_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=d.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=d.created_at::timestamptz
          AND s.expires_at::timestamptz>d.created_at::timestamptz
    ) THEN 'paid_indefinite' ELSE 'free_7d' END,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=d.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=d.created_at::timestamptz
          AND s.expires_at::timestamptz>d.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        d.created_at::timestamptz + INTERVAL '7 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=d.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=d.created_at::timestamptz
          AND s.expires_at::timestamptz>d.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        d.created_at::timestamptz + INTERVAL '14 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    NULL,
    CASE WHEN EXISTS (
        SELECT 1 FROM subscriptions s
        WHERE s.user_id=d.user_id AND s.tier<>'free'
          AND s.started_at::timestamptz<=d.created_at::timestamptz
          AND s.expires_at::timestamptz>d.created_at::timestamptz
    ) THEN NULL ELSE to_char(
        d.created_at::timestamptz + INTERVAL '44 days',
        'YYYY-MM-DD"T"HH24:MI:SS.USOF'
    ) END,
    NULL,d.created_at,to_char(NOW(),'YYYY-MM-DD"T"HH24:MI:SS.USOF'),
    'first-launch-2026-07-25'
FROM saved_diagnoses d
ON CONFLICT(content_type,content_id) DO NOTHING;

CREATE FUNCTION public.noteai_retained_primary_insert_guard_h20()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM 1
        FROM public.content_retention retention
        WHERE retention.content_type = TG_ARGV[0]
          AND retention.content_id = NEW.id
        FOR UPDATE;
    IF FOUND THEN
        RAISE EXCEPTION 'retained primary identity cannot be reinserted'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    public.noteai_retained_primary_insert_guard_h20()
    FROM PUBLIC;

CREATE TRIGGER notes_retained_primary_insert_h20
    BEFORE INSERT ON public.notes
    FOR EACH ROW
    EXECUTE FUNCTION public.noteai_retained_primary_insert_guard_h20('note');

CREATE TRIGGER saved_diagnoses_retained_primary_insert_h20
    BEFORE INSERT ON public.saved_diagnoses
    FOR EACH ROW
    EXECUTE FUNCTION public.noteai_retained_primary_insert_guard_h20(
        'diagnosis'
    );

ALTER TABLE content_retention ENABLE ROW LEVEL SECURITY;

CREATE POLICY content_retention_select_h17
    ON content_retention
    FOR SELECT
    TO PUBLIC
    USING (TRUE);

CREATE POLICY content_retention_insert_h20
    ON content_retention
    FOR INSERT
    TO PUBLIC
    WITH CHECK (
        purged_at IS NULL
        AND (
            (
                content_type = 'note'
                AND EXISTS (SELECT 1 FROM notes primary_note
                    WHERE primary_note.id = content_retention.content_id
                      AND primary_note.user_id = content_retention.user_id)
            )
            OR
            (
                content_type = 'diagnosis'
                AND EXISTS (
                    SELECT 1 FROM saved_diagnoses primary_diagnosis
                    WHERE primary_diagnosis.id = content_retention.content_id
                      AND primary_diagnosis.user_id = content_retention.user_id
                )
            )
        )
    );

CREATE POLICY content_retention_update_h17
    ON content_retention
    FOR UPDATE
    TO PUBLIC
    USING (purged_at IS NULL)
    WITH CHECK (
        purged_at IS NULL
        OR (
            btrim(purged_at)::timestamptz <= clock_timestamp()
            AND (
                (
                    content_type = 'note'
                    AND NOT EXISTS (SELECT 1 FROM notes primary_note
                        WHERE primary_note.id = content_retention.content_id
                          AND primary_note.user_id = content_retention.user_id)
                )
                OR
                (
                    content_type = 'diagnosis'
                    AND NOT EXISTS (SELECT 1 FROM saved_diagnoses primary_diagnosis
                        WHERE primary_diagnosis.id = content_retention.content_id
                          AND primary_diagnosis.user_id = content_retention.user_id)
                )
            )
        )
    );

CREATE TABLE IF NOT EXISTS account_deletion_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_ref TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    primary_inaccessible_at TEXT NOT NULL,
    primary_delete_by TEXT NOT NULL,
    backup_clear_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('requested','primary_deleted','backup_clear_pending','complete','cancelled')
    ),
    contract_version TEXT NOT NULL,
    primary_deleted_at TEXT,
    backup_cleared_at TEXT,
    backup_evidence_ref TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_account_deletion_open
    ON account_deletion_requests(user_id)
    WHERE status IN ('requested','primary_deleted','backup_clear_pending');

CREATE TABLE IF NOT EXISTS user_contract_acceptances (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contract_version TEXT NOT NULL,
    privacy_accepted_at TEXT NOT NULL,
    cross_border_notice_acknowledged_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('registration','account_settings')),
    PRIMARY KEY(user_id,contract_version)
);
CREATE INDEX IF NOT EXISTS idx_contract_acceptance_version
    ON user_contract_acceptances(contract_version,privacy_accepted_at);
