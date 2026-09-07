BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SET LOCAL search_path=pg_catalog,public;
SET LOCAL ROLE noteai_admin;
SELECT current_database() AS database_name,
       current_user AS verification_role,
       to_regclass('system_settings')='public.system_settings'::regclass AS search_path_binding,
       EXISTS (
         SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='public' AND c.relname='system_settings'
           AND c.relkind='r' AND c.relrowsecurity AND NOT c.relforcerowsecurity
       ) AS rls_contract_exact,
       (SELECT count(*) FROM public.schema_migrations WHERE version='0019_xhs_tracking_runtime_config.sql' AND sha256='bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f') AS ledger_exact_count,
       (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='system_settings' AND policyname='noteai_xhs_tracking_config_read_v1' AND permissive='PERMISSIVE' AND cmd='SELECT' AND with_check IS NULL AND cardinality(roles)=1 AND 'public'=ANY(roles)) AS policy_contract_count;
SELECT policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname='public' AND tablename='system_settings' AND policyname='noteai_xhs_tracking_config_read_v1';
ROLLBACK;
