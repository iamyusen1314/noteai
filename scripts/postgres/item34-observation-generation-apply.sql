-- PROSPECTIVE ONLY. Explicit owner apply of the matching native 0020 migration.
-- Deployment/predeploy with this source would also discover 0020; both stay PAUSED.
-- Future owner must bind expected_database and expected_owner in this session.
-- This installs schema/CAS only; it does not read XHS or open an observation.
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='5s';
SET LOCAL idle_in_transaction_session_timeout='90s';
SET LOCAL search_path=pg_catalog,public;
SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'));
DO $precondition$
BEGIN
  IF current_database() <> current_setting('noteai.item34.expected_database')
     OR current_user <> current_setting('noteai.item34.expected_owner') THEN
    RAISE EXCEPTION 'ITEM34_GENERATION_REJECTED: database or owner binding';
  END IF;
  IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relname IN
        ('tracked_notes','tracking_provider_attempts','schema_migrations')
        AND c.relkind='r' AND pg_get_userbyid(c.relowner)=current_user) <> 3 THEN
    RAISE EXCEPTION 'ITEM34_GENERATION_REJECTED: actual table owner mismatch';
  END IF;
  IF (SELECT count(*) FROM public.schema_migrations
      WHERE version='0019_xhs_tracking_runtime_config.sql'
        AND sha256='bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f') <> 1
     OR EXISTS (SELECT 1 FROM public.schema_migrations
                WHERE version='0020_tracking_observation_generation.sql') THEN
    RAISE EXCEPTION 'ITEM34_GENERATION_REJECTED: migration history';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='public.tracked_notes'::regclass
             AND attname='observation_generation' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'ITEM34_GENERATION_REJECTED: schema already present';
  END IF;
END
$precondition$;
-- DDL_PAYLOAD_BEGIN
ALTER TABLE public.tracked_notes
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
ALTER TABLE public.tracking_provider_attempts
    ADD COLUMN observation_generation INTEGER NOT NULL DEFAULT 0
        CHECK (observation_generation >= 0),
    DROP CONSTRAINT tracking_provider_attempt_one_per_stage,
    ADD CONSTRAINT tracking_provider_attempt_one_per_generation_stage
        UNIQUE(track_id, observation_generation, stage),
    ADD CONSTRAINT tracking_provider_attempt_generation_identity
        UNIQUE(track_id, observation_generation, id);
-- Keep the original owner/history FK. Only the ACTIVE pointer follows current
-- generation; an old worker's default-generation INSERT cannot be activated.
ALTER TABLE public.tracked_notes
    DROP CONSTRAINT tracked_notes_active_attempt_fk,
    ADD CONSTRAINT tracked_notes_active_attempt_fk
        FOREIGN KEY(id, observation_generation, active_attempt_id)
        REFERENCES public.tracking_provider_attempts(track_id, observation_generation, id)
        DEFERRABLE INITIALLY DEFERRED;

-- Existing API table-level privileges must not silently confer control of the
-- new metadata. Ordinary inserts/defaults and existing-column writes stay valid.
CREATE FUNCTION public.noteai_item34_observation_owner_guard() RETURNS trigger
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
REVOKE ALL ON FUNCTION public.noteai_item34_observation_owner_guard() FROM PUBLIC;
CREATE TRIGGER item34_observation_owner_guard BEFORE INSERT OR UPDATE ON public.tracked_notes
    FOR EACH ROW EXECUTE FUNCTION public.noteai_item34_observation_owner_guard();

CREATE FUNCTION public.noteai_item34_open_observation(
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
REVOKE ALL ON FUNCTION public.noteai_item34_open_observation(TEXT,TEXT,INTEGER,TEXT,TIMESTAMPTZ,JSONB)
    FROM PUBLIC;
-- DDL_PAYLOAD_END
INSERT INTO public.schema_migrations(version,sha256)
VALUES('0020_tracking_observation_generation.sql','22ef0a2c21529fe4d8ed38c42c2283ae61e6e6822d6411bd07620d353042d7a9');
COMMIT;
