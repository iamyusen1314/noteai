-- Repeatable read-only reconciliation after a known or unknown apply result.
-- A mismatch is not permission to reapply or remove historical state.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SET LOCAL search_path=pg_catalog,public;
SELECT current_database() AS database_name,current_user AS verification_role,
       (SELECT count(*) FROM public.schema_migrations WHERE
        version='0020_tracking_observation_generation.sql' AND
        sha256='22ef0a2c21529fe4d8ed38c42c2283ae61e6e6822d6411bd07620d353042d7a9') AS exact_ledger_count,
       (SELECT count(*) FROM pg_attribute WHERE NOT attisdropped AND
        attrelid IN ('public.tracked_notes'::regclass,'public.tracking_provider_attempts'::regclass)
        AND attname='observation_generation' AND atttypid='integer'::regtype AND attnotnull) AS generation_column_count,
       (SELECT count(*) FROM pg_trigger WHERE tgrelid='public.tracked_notes'::regclass
        AND tgname='item34_observation_owner_guard' AND tgenabled='O') AS owner_guard_count;
SELECT c.relname AS table_name,a.attname,format_type(a.atttypid,a.atttypmod) AS type,
       a.attnotnull,pg_get_expr(d.adbin,d.adrelid) AS default_expression
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE a.attrelid IN ('public.tracked_notes'::regclass,'public.tracking_provider_attempts'::regclass)
  AND NOT a.attisdropped AND a.attname IN
    ('observation_generation','observation_started_at','observation_initial_snapshot')
ORDER BY c.relname,a.attname;
SELECT pg_get_triggerdef(t.oid) AS definition,t.tgfoid::regprocedure AS function,
       n.nspname AS function_schema,p.proname AS function_name,t.tgenabled
FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE t.tgrelid='public.tracked_notes'::regclass AND t.tgname='item34_observation_owner_guard';
SELECT conname,pg_get_constraintdef(oid) AS definition,convalidated,condeferrable,condeferred
FROM pg_constraint WHERE conrelid IN
  ('public.tracked_notes'::regclass,'public.tracking_provider_attempts'::regclass)
  AND conname IN ('tracked_observation_anchor','tracked_notes_active_attempt_fk',
                 'tracking_provider_attempt_one_per_generation_stage','tracking_provider_attempt_generation_identity')
ORDER BY conname;
SELECT p.proname,pg_get_userbyid(p.proowner) AS function_owner,p.prosecdef AS security_definer,
       p.proconfig,pg_get_functiondef(p.oid) AS definition,
       EXISTS (SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner)))
               WHERE grantee=0 AND privilege_type='EXECUTE') AS public_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname IN
 ('noteai_item34_open_observation','noteai_item34_observation_owner_guard')
ORDER BY p.proname;
ROLLBACK;
