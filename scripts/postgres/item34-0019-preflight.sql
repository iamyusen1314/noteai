BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SET LOCAL search_path=pg_catalog,public;
SELECT current_database() AS database_name,
       to_regclass('public.system_settings') IS NOT NULL AS settings_present,
       to_regclass('public.schema_migrations') IS NOT NULL AS ledger_present,
       to_regclass('system_settings')='public.system_settings'::regclass AS search_path_binding,
       pg_has_role(session_user,'noteai_admin','SET') AS owner_activation_capable;
SET LOCAL ROLE noteai_admin;
SELECT current_user='noteai_admin' AS owner_active,
       EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='system_settings' AND tableowner='noteai_admin') AS settings_owner_exact,
       EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='schema_migrations' AND tableowner='noteai_admin') AS ledger_owner_exact,
       EXISTS (
         SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='public' AND c.relname='system_settings'
           AND c.relkind='r' AND c.relrowsecurity AND NOT c.relforcerowsecurity
       ) AS rls_contract_exact,
       (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='system_settings' AND policyname='noteai_xhs_tracking_config_read_v1')=0 AS policy_absent,
       (SELECT count(*) FROM public.schema_migrations WHERE version='0019_xhs_tracking_runtime_config.sql')=0 AS ledger_absent;
ROLLBACK;
