BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='5s';
SET LOCAL idle_in_transaction_session_timeout='90s';
SET LOCAL ROLE noteai_admin;
SET LOCAL search_path=pg_catalog,public;
SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'));
DO $item34_precondition$
BEGIN
  IF current_user <> 'noteai_admin' THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: owner role inactive';
  END IF;
  IF to_regclass('system_settings') <> 'public.system_settings'::regclass THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: search_path binding';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='system_settings' AND tableowner='noteai_admin') THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: system_settings owner mismatch';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='schema_migrations' AND tableowner='noteai_admin') THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: schema_migrations owner mismatch';
  END IF;
  IF NOT (EXISTS (
         SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='public' AND c.relname='system_settings'
           AND c.relkind='r' AND c.relrowsecurity AND NOT c.relforcerowsecurity
       )) THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: RLS contract mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='system_settings' AND policyname='noteai_xhs_tracking_config_read_v1') THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: policy already present';
  END IF;
  IF EXISTS (SELECT 1 FROM public.schema_migrations WHERE version='0019_xhs_tracking_runtime_config.sql') THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: ledger already present';
  END IF;
END
$item34_precondition$;
SET LOCAL TIME ZONE 'UTC';

-- The dedicated Tracking role needs its non-secret runtime switch and the
-- existing cross-run session stop flag.  Keep the
-- policy independent of role creation order, as earlier runtime policies do.
DROP POLICY IF EXISTS noteai_xhs_tracking_config_read_v1
    ON system_settings;
CREATE POLICY noteai_xhs_tracking_config_read_v1
    ON system_settings
FOR SELECT TO PUBLIC
USING (
    current_user = 'noteai_xhs_tracking'
    AND is_secret = 0
    AND key IN ('crawler_config', 'xhs_collection_safety')
);

INSERT INTO public.schema_migrations(version,sha256)
VALUES('0019_xhs_tracking_runtime_config.sql','bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f');
DO $item34_postcondition$
BEGIN
  IF (SELECT count(*) FROM public.schema_migrations WHERE version='0019_xhs_tracking_runtime_config.sql' AND sha256='bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f') <> 1 THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: ledger postcondition';
  END IF;
  IF NOT (EXISTS (
         SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='public' AND c.relname='system_settings'
           AND c.relkind='r' AND c.relrowsecurity AND NOT c.relforcerowsecurity
       )) THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: RLS postcondition';
  END IF;
  IF (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='system_settings' AND policyname='noteai_xhs_tracking_config_read_v1' AND permissive='PERMISSIVE' AND cmd='SELECT' AND with_check IS NULL AND cardinality(roles)=1 AND 'public'=ANY(roles)) <> 1 THEN
    RAISE EXCEPTION 'ITEM34_0019_REJECTED: policy postcondition';
  END IF;
END
$item34_postcondition$;
COMMIT;
