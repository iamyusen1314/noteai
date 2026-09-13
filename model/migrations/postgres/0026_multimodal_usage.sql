-- Disjoint audio input dimensions in the original per-call cost ledger.
-- No historical cost/token reconstruction; old non-audio calls retain zero
-- audio dimensions and NULL price snapshots. No supplier activation here.
ALTER TABLE public.model_usage_records
    ADD COLUMN audio_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(audio_input_tokens>=0),
    ADD COLUMN audio_cache_read_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(audio_cache_read_input_tokens>=0),
    ADD COLUMN audio_input_price_per_1m DOUBLE PRECISION,
    ADD COLUMN audio_cache_read_price_per_1m DOUBLE PRECISION;

-- Preserve full original video/audio in the existing owner-bound media store.
-- No legacy row, original object, observation or supplier request is rewritten.
ALTER TABLE public.private_media_refs
    DROP CONSTRAINT private_media_refs_purpose_check,
    DROP CONSTRAINT private_media_refs_check,
    DROP CONSTRAINT private_media_refs_check1,
    DROP CONSTRAINT private_media_refs_check2,
    ADD CONSTRAINT private_media_refs_purpose_check CHECK(purpose IN ('image','video_frames','video')),
    ADD CONSTRAINT private_media_refs_check CHECK(
        (purpose='image' AND content_type IN ('image/jpeg','image/png','image/webp')) OR
        (purpose='video_frames' AND content_type='application/vnd.noteai.video-frames+zip') OR
        (purpose='video' AND content_type IN ('video/mp4','video/quicktime','video/x-msvideo'))),
    ADD CONSTRAINT private_media_refs_check1 CHECK(
        (purpose='image' AND size_bytes BETWEEN 1 AND 10485760) OR
        (purpose='video_frames' AND size_bytes BETWEEN 1 AND 67108864) OR
        (purpose='video' AND size_bytes BETWEEN 1 AND 104857600)),
    ADD CONSTRAINT private_media_refs_check2 CHECK(
        (purpose IN ('image','video') AND item_count=1) OR
        (purpose='video_frames' AND item_count BETWEEN 1 AND 100)),
    ADD COLUMN ark_state TEXT NOT NULL DEFAULT 'none' CHECK(ark_state IN ('none','uploading','uploaded','active','inference','unknown','failed','delete_pending','deleted')),
    ADD COLUMN ark_file_id TEXT CHECK(ark_file_id IS NULL OR ark_file_id ~ '^file-[A-Za-z0-9_-]{1,128}$'),
    ADD COLUMN ark_claim_id TEXT CHECK(ark_claim_id IS NULL OR ark_claim_id ~ '^[0-9a-f-]{36}$'),
    ADD COLUMN ark_model TEXT CHECK(ark_model IS NULL OR ark_model='doubao-seed-2-0-lite-260428'),
    ADD COLUMN ark_expires_at BIGINT CHECK(ark_expires_at IS NULL OR ark_expires_at BETWEEN 946684800 AND 4102444800),
    ADD COLUMN ark_call_hash TEXT CHECK(ark_call_hash IS NULL OR ark_call_hash ~ '^[0-9a-f]{64}$'),
    ADD COLUMN ark_updated_at TEXT,
    ADD CONSTRAINT private_media_ark_binding CHECK(
        (ark_state='none' AND ark_file_id IS NULL AND ark_claim_id IS NULL AND ark_model IS NULL AND ark_expires_at IS NULL AND ark_call_hash IS NULL AND ark_updated_at IS NULL) OR
        (purpose='video' AND ark_state<>'none' AND ark_claim_id IS NOT NULL AND ark_model IS NOT NULL AND ark_expires_at IS NOT NULL AND ark_updated_at IS NOT NULL
         AND (ark_state NOT IN ('uploaded','active','inference','delete_pending','deleted') OR ark_file_id IS NOT NULL)));

CREATE FUNCTION public.noteai_guard_ark_media_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE
    cols TEXT[] := ARRAY['ark_state','ark_file_id','ark_claim_id','ark_model','ark_expires_at','ark_call_hash','ark_updated_at'];
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.ark_state<>'none' THEN RAISE EXCEPTION 'initial Ark state must be none' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    IF to_jsonb(NEW)-cols-ARRAY['state','deleted_at'] IS DISTINCT FROM to_jsonb(OLD)-cols-ARRAY['state','deleted_at'] THEN
        RAISE EXCEPTION 'immutable original media binding' USING ERRCODE='23514';
    END IF;
    IF NEW.ark_state=OLD.ark_state THEN
        IF ROW(NEW.ark_file_id,NEW.ark_claim_id,NEW.ark_model,NEW.ark_expires_at,NEW.ark_call_hash,NEW.ark_updated_at) IS DISTINCT FROM
           ROW(OLD.ark_file_id,OLD.ark_claim_id,OLD.ark_model,OLD.ark_expires_at,OLD.ark_call_hash,OLD.ark_updated_at) THEN
            RAISE EXCEPTION 'Ark metadata without state transition' USING ERRCODE='23514';
        END IF;
        IF ROW(NEW.state,NEW.deleted_at) IS DISTINCT FROM ROW(OLD.state,OLD.deleted_at) AND NOT (OLD.state='ready' AND NEW.state IN ('expired','deleted') AND NEW.deleted_at IS NOT NULL AND NEW.ark_state IN ('none','failed','deleted')) THEN
            RAISE EXCEPTION 'remote media cleanup unconfirmed' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state<>'ready' OR NEW.state<>OLD.state OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at OR NOT (
        (OLD.ark_state='none' AND NEW.ark_state='uploading') OR
        (OLD.ark_state='uploading' AND NEW.ark_state IN ('uploaded','unknown','failed')) OR
        (OLD.ark_state='uploaded' AND NEW.ark_state IN ('active','delete_pending')) OR
        (OLD.ark_state='active' AND NEW.ark_state IN ('inference','delete_pending')) OR
        (OLD.ark_state='inference' AND NEW.ark_state IN ('active','unknown')) OR
        (OLD.ark_state='delete_pending' AND NEW.ark_state='deleted')) THEN
        RAISE EXCEPTION 'invalid Ark lifecycle transition' USING ERRCODE='23514';
    END IF;
    IF OLD.ark_state<>'none' AND ROW(NEW.ark_claim_id,NEW.ark_model,NEW.ark_expires_at) IS DISTINCT FROM ROW(OLD.ark_claim_id,OLD.ark_model,OLD.ark_expires_at) THEN
        RAISE EXCEPTION 'immutable Ark upload claim' USING ERRCODE='23514';
    END IF;
    IF OLD.ark_file_id IS NOT NULL AND NEW.ark_file_id IS DISTINCT FROM OLD.ark_file_id THEN
        RAISE EXCEPTION 'immutable Ark file identity' USING ERRCODE='23514';
    END IF;
    IF NOT (OLD.ark_state='active' AND NEW.ark_state='inference') AND NEW.ark_call_hash IS DISTINCT FROM OLD.ark_call_hash THEN
        RAISE EXCEPTION 'invalid Ark inference binding' USING ERRCODE='23514';
    END IF;
    IF NEW.ark_state='inference' AND NEW.ark_call_hash IS NULL THEN
        RAISE EXCEPTION 'missing Ark inference binding' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER noteai_guard_ark_media_v1 BEFORE INSERT OR UPDATE ON public.private_media_refs
FOR EACH ROW EXECUTE FUNCTION public.noteai_guard_ark_media_v1();
CREATE POLICY noteai_private_media_ark_v1 ON public.private_media_refs FOR UPDATE TO PUBLIC
USING(current_user='noteai_app' AND purpose='video' AND state='ready')
WITH CHECK(current_user='noteai_app' AND purpose='video' AND state='ready' AND deleted_at IS NULL);
GRANT UPDATE(ark_state,ark_file_id,ark_claim_id,ark_model,ark_expires_at,ark_call_hash,ark_updated_at)
ON public.private_media_refs TO noteai_app;

-- The existing screenshot admission owns its result digest and one included
-- merge. No response content is stored here; old admissions remain unchanged.
ALTER TABLE public.idempotency_requests
  ADD COLUMN ocr_result_hash TEXT CHECK (ocr_result_hash IS NULL OR
    (operation='screenshot' AND status='completed' AND complete_applied=1 AND refund_applied=0
     AND ocr_result_hash ~ '^[0-9a-f]{64}$')),
  ADD COLUMN ocr_merge_key_hash TEXT CHECK (ocr_merge_key_hash IS NULL OR
    (ocr_result_hash IS NOT NULL AND ocr_merge_key_hash ~ '^[0-9a-f]{64}$'));
GRANT SELECT(ocr_result_hash,ocr_merge_key_hash),UPDATE(ocr_result_hash,ocr_merge_key_hash)
ON public.idempotency_requests TO noteai_app;
