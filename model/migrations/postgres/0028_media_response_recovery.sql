-- Original screenshot claims retain an opaque private-result reference.
-- No result body, historical response backfill, new task queue or provider call.
ALTER TABLE public.idempotency_requests ADD COLUMN response_ref_json TEXT
  CHECK(response_ref_json IS NULL OR (length(response_ref_json)<=4096
    AND jsonb_typeof(response_ref_json::jsonb)='object'));
CREATE INDEX idx_idempotency_response_reference
  ON public.idempotency_requests((response_ref_json::jsonb->>'id'))
  WHERE response_ref_json IS NOT NULL;
CREATE FUNCTION public.noteai_guard_response_reference_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE old_ref jsonb; new_ref jsonb;
BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.response_ref_json IS NOT NULL AND OLD.response_ref_json::jsonb->>'state'='ready' THEN
   RAISE EXCEPTION 'private response cleanup required' USING ERRCODE='23514';
  END IF;
  RETURN OLD;
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.response_ref_json IS NOT NULL THEN
   RAISE EXCEPTION 'response requires completed original claim' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.response_ref_json IS NOT DISTINCT FROM OLD.response_ref_json THEN RETURN NEW; END IF;
 new_ref := NEW.response_ref_json::jsonb;
 old_ref := OLD.response_ref_json::jsonb;
 IF new_ref IS NULL OR NEW.operation<>'screenshot' OR NEW.status<>'completed'
   OR NEW.complete_applied<>1 OR NEW.refund_applied<>0
   OR new_ref->>'operation_id' IS DISTINCT FROM NEW.id OR new_ref->>'purpose' IS DISTINCT FROM 'result'
   OR (SELECT count(*) FROM jsonb_object_keys(new_ref))<>16
   OR new_ref - ARRAY['id','operation_id','subject_hash','purpose','object_key_hash','content_sha256',
      'size_bytes','item_count','schema_version','encryption_mode','key_epoch_hash','state',
      'expires_at','created_at','ready_at','deleted_at'] <> '{}'::jsonb THEN
  RAISE EXCEPTION 'invalid response binding' USING ERRCODE='23514';
 END IF;
 IF old_ref IS NULL THEN
  IF new_ref->>'state' IS DISTINCT FROM 'ready' OR new_ref->>'deleted_at' IS NOT NULL THEN
   RAISE EXCEPTION 'invalid initial response state' USING ERRCODE='23514';
  END IF;
 ELSIF new_ref - ARRAY['state','deleted_at'] IS DISTINCT FROM old_ref - ARRAY['state','deleted_at']
   OR old_ref->>'state' IS DISTINCT FROM 'ready' OR new_ref->>'state' IS NULL
   OR new_ref->>'state' NOT IN ('deleted','expired')
   OR new_ref->>'deleted_at' IS NULL THEN
  RAISE EXCEPTION 'immutable response reference' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER noteai_guard_response_reference_v1 BEFORE INSERT OR UPDATE OR DELETE
ON public.idempotency_requests FOR EACH ROW EXECUTE FUNCTION public.noteai_guard_response_reference_v1();
GRANT SELECT(response_ref_json), UPDATE(response_ref_json) ON public.idempotency_requests TO noteai_app;
