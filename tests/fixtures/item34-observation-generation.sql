-- Prospective schema/CAS design, executable ONLY in the disposable PG16 test.
-- Not an approved migration; not discovered by render_predeploy. No live T0,
-- identity, role grant, supplier call, old-window replay or ledger entry here.
DO $$ BEGIN
    IF current_database() !~ '^noteai_item34_test_[0-9a-f]+$' THEN
        RAISE EXCEPTION 'isolated Item34 proposal database required';
    END IF;
END $$;

ALTER TABLE tracked_notes
    ADD COLUMN observation_generation INTEGER NOT NULL DEFAULT 0
        CHECK (observation_generation >= 0),
    ADD COLUMN observation_started_at TEXT,
    ADD COLUMN observation_initial_snapshot JSONB,
    ADD CONSTRAINT tracked_observation_anchor CHECK (
        observation_generation = 0 OR (
            observation_started_at IS NOT NULL
            AND observation_started_at::timestamptz IS NOT NULL
            AND observation_initial_snapshot IS NOT NULL
            AND jsonb_typeof(observation_initial_snapshot) = 'object'
        )
    );
ALTER TABLE tracking_provider_attempts
    ADD COLUMN observation_generation INTEGER NOT NULL DEFAULT 0
        CHECK (observation_generation >= 0),
    DROP CONSTRAINT tracking_provider_attempt_one_per_stage,
    ADD CONSTRAINT tracking_provider_attempt_one_per_generation_stage
        UNIQUE(track_id, observation_generation, stage),
    ADD CONSTRAINT tracking_provider_attempt_generation_identity
        UNIQUE(track_id, observation_generation, id);
-- Keep the original owner/history FK. Only the ACTIVE pointer follows current
-- generation; an old worker's default-generation INSERT cannot be activated.
ALTER TABLE tracked_notes
    DROP CONSTRAINT tracked_notes_active_attempt_fk,
    ADD CONSTRAINT tracked_notes_active_attempt_fk
        FOREIGN KEY(id, observation_generation, active_attempt_id)
        REFERENCES tracking_provider_attempts(track_id, observation_generation, id)
        DEFERRABLE INITIALLY DEFERRED;

-- Existing API table-level privileges must not silently confer control of the
-- new metadata. Ordinary inserts/defaults and existing-column writes stay valid.
CREATE FUNCTION noteai_item34_observation_owner_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.observation_generation = 0 AND NEW.observation_started_at IS NULL
           AND NEW.observation_initial_snapshot IS NULL THEN RETURN NEW; END IF;
    ELSIF ROW(NEW.observation_generation,NEW.observation_started_at,NEW.observation_initial_snapshot)
        IS NOT DISTINCT FROM
        ROW(OLD.observation_generation,OLD.observation_started_at,OLD.observation_initial_snapshot) THEN
        RETURN NEW;
    END IF;
    IF current_user <> (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid=TG_RELID) THEN
        RAISE EXCEPTION 'observation metadata requires table owner';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION noteai_item34_observation_owner_guard() FROM PUBLIC;
CREATE TRIGGER item34_observation_owner_guard BEFORE INSERT OR UPDATE ON tracked_notes
    FOR EACH ROW EXECUTE FUNCTION noteai_item34_observation_owner_guard();

CREATE FUNCTION noteai_item34_open_observation(
    target_track TEXT, target_owner TEXT, previous_generation INTEGER,
    previous_failed_attempt TEXT, new_t0 TIMESTAMPTZ, initial_snapshot JSONB
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    target public.tracked_notes%ROWTYPE;
    prior public.tracking_provider_attempts%ROWTYPE;
    metric TEXT;
BEGIN
    IF previous_generation IS NULL OR previous_generation < 0
       OR new_t0 IS NULL OR new_t0 > clock_timestamp()
       OR initial_snapshot IS NULL OR jsonb_typeof(initial_snapshot) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(initial_snapshot)) <> 3 THEN
        RAISE EXCEPTION 'invalid prospective observation input';
    END IF;
    FOREACH metric IN ARRAY ARRAY['likes','saves','comments'] LOOP
        IF NOT initial_snapshot ? metric
           OR jsonb_typeof(initial_snapshot->metric) <> 'number'
           OR initial_snapshot->>metric !~ '^[0-9]+$'
           OR (initial_snapshot->>metric)::numeric > 2147483647 THEN
            RAISE EXCEPTION 'invalid prospective initial metrics';
        END IF;
    END LOOP;
    PERFORM pg_advisory_xact_lock(hashtext('noteai:user-write:' || target_owner));
    SELECT * INTO target FROM public.tracked_notes
        WHERE id=target_track AND user_id=target_owner FOR UPDATE;
    IF NOT FOUND OR target.observation_generation <> previous_generation
       OR target.status <> 'needs_manual' OR target.active_attempt_id IS NOT NULL
       OR target.claim_token IS NOT NULL OR target.claim_expires_at IS NOT NULL
       OR target.next_check_at IS NOT NULL OR target.attempt_count <> 1
       OR target.check_24h_at IS NOT NULL OR target.check_7d_at IS NOT NULL
       OR target.completed_at IS NOT NULL OR target.likes_24h IS NOT NULL
       OR target.saves_24h IS NOT NULL OR target.comments_24h IS NOT NULL
       OR target.likes_7d IS NOT NULL OR target.saves_7d IS NOT NULL
       OR target.comments_7d IS NOT NULL OR new_t0 <= target.submitted_at::timestamptz THEN
        RAISE EXCEPTION 'prospective observation CAS rejected';
    END IF;
    SELECT * INTO prior FROM public.tracking_provider_attempts
        WHERE id=previous_failed_attempt AND track_id=target_track
          AND user_id=target_owner AND observation_generation=previous_generation;
    IF NOT FOUND OR prior.status <> 'failed' OR prior.stage <> '24h'
       OR prior.error_code IS NULL OR prior.error_code = 'provider_outcome_unknown'
       OR prior.completed_at::timestamptz >= new_t0
       OR (SELECT count(*) FROM public.tracking_provider_attempts
           WHERE track_id=target_track AND observation_generation=previous_generation) <> 1 THEN
        RAISE EXCEPTION 'prior failed observation not reconciled';
    END IF;
    -- Same order as crawler admission: user/track, global observation, UTC cap.
    PERFORM pg_advisory_xact_lock(hashtext('noteai:tracking:observation-open'));
    IF EXISTS (SELECT 1 FROM public.tracking_provider_attempts WHERE status='started'
               OR (status='failed' AND error_code='provider_outcome_unknown')) THEN
        RAISE EXCEPTION 'global provider outcome unresolved';
    END IF;
    UPDATE public.tracked_notes SET
        observation_generation=previous_generation+1,
        observation_started_at=to_char(new_t0 AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        observation_initial_snapshot=initial_snapshot,
        next_check_at=to_char((new_t0+interval '24 hours') AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        status='pending', attempt_count=0, last_checked_at=NULL,
        last_error=NULL, last_error_code=NULL
        WHERE id=target_track AND user_id=target_owner
          AND observation_generation=previous_generation;
    RETURN previous_generation+1;
END $$;
REVOKE ALL ON FUNCTION noteai_item34_open_observation(TEXT,TEXT,INTEGER,TEXT,TIMESTAMPTZ,JSONB)
    FROM PUBLIC;
