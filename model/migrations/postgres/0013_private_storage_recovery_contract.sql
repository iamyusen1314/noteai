SET LOCAL TIME ZONE 'UTC';

-- Repository contract only. Runtime roles receive no privileges here.
-- Raw media, object keys, URLs, filenames, user identifiers, credentials and
-- restore contents are intentionally absent.

CREATE TABLE IF NOT EXISTS private_media_refs (
    id                  TEXT PRIMARY KEY
                        CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    subject_hash        TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    purpose             TEXT NOT NULL CHECK (purpose IN ('image','video_frames')),
    content_type        TEXT NOT NULL CHECK (
                            (purpose = 'image' AND content_type IN (
                                'image/jpeg','image/png','image/webp'
                            ))
                            OR (
                                purpose = 'video_frames'
                                AND content_type = 'application/vnd.noteai.video-frames+zip'
                            )
                        ),
    object_key_hash     TEXT NOT NULL CHECK (object_key_hash ~ '^[0-9a-f]{64}$'),
    content_sha256      TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes          BIGINT NOT NULL CHECK (
                            (purpose = 'image' AND size_bytes BETWEEN 1 AND 10485760)
                            OR (
                                purpose = 'video_frames'
                                AND size_bytes BETWEEN 1 AND 67108864
                            )
                        ),
    item_count          INTEGER NOT NULL CHECK (
                            (purpose = 'image' AND item_count = 1)
                            OR (purpose = 'video_frames' AND item_count BETWEEN 1 AND 100)
                        ),
    schema_version      INTEGER NOT NULL CHECK (schema_version BETWEEN 1 AND 16),
    encryption_mode     TEXT NOT NULL CHECK (
                            encryption_mode IN ('provider_managed','envelope_aes256')
                        ),
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

CREATE INDEX IF NOT EXISTS idx_private_media_refs_subject
    ON private_media_refs(subject_hash, state, expires_at);
CREATE INDEX IF NOT EXISTS idx_private_media_refs_lifecycle
    ON private_media_refs(state, expires_at, purpose);

CREATE TABLE IF NOT EXISTS ai_operation_media_refs (
    operation_id        TEXT NOT NULL
                        REFERENCES ai_operations(id) ON DELETE RESTRICT,
    media_ref_id        TEXT NOT NULL
                        REFERENCES private_media_refs(id) ON DELETE RESTRICT,
    ordinal             INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 9),
    created_at          TEXT NOT NULL CHECK (
                            created_at = btrim(created_at)
                            AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$'
                            AND created_at::timestamptz IS NOT NULL
                        ),
    PRIMARY KEY(operation_id, media_ref_id),
    UNIQUE(operation_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_ai_operation_media_refs_media
    ON ai_operation_media_refs(media_ref_id, operation_id);

CREATE OR REPLACE FUNCTION noteai_validate_operation_media_link_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    operation_subject TEXT;
    media_subject TEXT;
    media_state TEXT;
    media_ready_at TEXT;
    media_expires_at TEXT;
BEGIN
    SELECT o.subject_hash,m.subject_hash,m.state,m.ready_at,m.expires_at
    INTO operation_subject,media_subject,media_state,media_ready_at,media_expires_at
    FROM public.ai_operations o
    JOIN public.private_media_refs m ON m.id=NEW.media_ref_id
    WHERE o.id=NEW.operation_id;

    IF NOT FOUND
       OR operation_subject <> media_subject
       OR media_state <> 'ready'
       OR media_ready_at::timestamptz > NEW.created_at::timestamptz
       OR media_expires_at::timestamptz <= NEW.created_at::timestamptz THEN
        RAISE EXCEPTION 'invalid owner-bound media link'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS noteai_operation_media_owner_guard_v1
    ON ai_operation_media_refs;
CREATE TRIGGER noteai_operation_media_owner_guard_v1
BEFORE INSERT ON ai_operation_media_refs
FOR EACH ROW
EXECUTE FUNCTION noteai_validate_operation_media_link_v1();

ALTER TABLE private_media_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_operation_media_refs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS noteai_private_media_select_v1 ON private_media_refs;
CREATE POLICY noteai_private_media_select_v1 ON private_media_refs
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_app','noteai_ai_worker'));

DROP POLICY IF EXISTS noteai_private_media_api_insert_v1 ON private_media_refs;
CREATE POLICY noteai_private_media_api_insert_v1 ON private_media_refs
FOR INSERT TO PUBLIC
WITH CHECK (
    current_user = 'noteai_app'
    AND state = 'ready'
    AND deleted_at IS NULL
);

DROP POLICY IF EXISTS noteai_private_media_api_lifecycle_v1 ON private_media_refs;
CREATE POLICY noteai_private_media_api_lifecycle_v1 ON private_media_refs
FOR UPDATE TO PUBLIC
USING (
    current_user = 'noteai_app'
    AND state = 'ready'
)
WITH CHECK (
    current_user = 'noteai_app'
    AND state IN ('expired','deleted')
    AND deleted_at IS NOT NULL
);

DROP POLICY IF EXISTS noteai_operation_media_select_v1 ON ai_operation_media_refs;
CREATE POLICY noteai_operation_media_select_v1 ON ai_operation_media_refs
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_app','noteai_ai_worker'));

DROP POLICY IF EXISTS noteai_operation_media_api_insert_v1 ON ai_operation_media_refs;
CREATE POLICY noteai_operation_media_api_insert_v1 ON ai_operation_media_refs
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_app');
