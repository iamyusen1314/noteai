-- Read-only metadata for the prospective 0020 scope. No object state is changed.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SET LOCAL search_path=pg_catalog,public;
SELECT current_database() AS database_name, current_user AS active_role,
       session_user AS session_role, clock_timestamp() AS observed_at,
       current_setting('server_version_num')::int AS server_version_num;
SELECT c.relname AS table_name, pg_get_userbyid(c.relowner) AS actual_owner,
       pg_has_role(session_user,c.relowner,'SET') AS owner_activation_capable,
       c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS force_rls
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname IN
  ('tracked_notes','tracking_provider_attempts','schema_migrations')
ORDER BY c.relname;
SELECT version,sha256 FROM public.schema_migrations WHERE version >= '0019' ORDER BY version;
SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint
WHERE conrelid IN ('public.tracked_notes'::regclass,'public.tracking_provider_attempts'::regclass)
  AND conname IN ('tracked_notes_active_attempt_fk','tracking_provider_attempt_one_per_stage',
                 'tracking_provider_attempt_one_per_generation_stage','tracking_provider_attempt_generation_identity')
ORDER BY conname;
SELECT count(*) FILTER (WHERE status='started') AS global_started,
       count(*) FILTER (WHERE status='failed' AND error_code='provider_outcome_unknown') AS global_unknown,
       count(*) FILTER (WHERE admitted_at::timestamptz >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC') AS admitted_today_utc
FROM public.tracking_provider_attempts;
ROLLBACK;
