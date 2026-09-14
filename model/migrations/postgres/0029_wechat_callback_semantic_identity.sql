-- Keep original notification hashes and old events unchanged. Only newly
-- authenticated WeChat callbacks may bind the complete decrypted resource.
ALTER TABLE payment_events
    ADD COLUMN event_semantic_sha256 TEXT
        CHECK (event_semantic_sha256 IS NULL
               OR event_semantic_sha256 ~ '^[0-9a-f]{64}$');

CREATE FUNCTION noteai_payment_event_semantic_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.event_semantic_sha256 IS DISTINCT FROM OLD.event_semantic_sha256 THEN
        RAISE EXCEPTION 'payment event semantic identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER payment_events_semantic_immutable_v1
BEFORE UPDATE OF event_semantic_sha256 ON payment_events
FOR EACH ROW EXECUTE FUNCTION noteai_payment_event_semantic_guard_v1();

REVOKE ALL ON FUNCTION noteai_payment_event_semantic_guard_v1() FROM PUBLIC;
-- Existing Payment SELECT/INSERT cover the new column. Do not grant UPDATE,
-- change RLS, backfill historical fingerprints or alter the original guards.
