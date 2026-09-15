-- No snapshot is inserted here. The operator binds the actual current account
-- observation before enabling Amap. Runtime cannot create/reset a monthly bucket.
CREATE TABLE public.amap_quota_buckets (
 account_scope TEXT NOT NULL CHECK(account_scope='noteai-primary-amap-account'),
 service_group TEXT NOT NULL CHECK(service_group='basic_search'),
 period TEXT NOT NULL CHECK(period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
 period_start TEXT NOT NULL, period_end TEXT NOT NULL,
 time_zone TEXT NOT NULL CHECK(time_zone='Asia/Shanghai'),
 quota INTEGER NOT NULL CHECK(quota BETWEEN 1 AND 1000000000),
 official_used INTEGER NOT NULL CHECK(official_used BETWEEN 0 AND quota),
 observed_at TEXT NOT NULL, source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 500),
 snapshot_sha256 TEXT NOT NULL CHECK(snapshot_sha256 ~ '^[0-9a-f]{64}$'),
 owner_authorized_at TEXT NOT NULL,
 enterprise_certified INTEGER NOT NULL CHECK(enterprise_certified=1),
 license_purchased INTEGER NOT NULL CHECK(license_purchased=0),
 owner_risk_accepted INTEGER NOT NULL CHECK(owner_risk_accepted=1),
 exclusive_noteai_use INTEGER NOT NULL CHECK(exclusive_noteai_use=1),
 billing_observation_json TEXT CHECK(billing_observation_json IS NULL OR
   (octet_length(billing_observation_json)<=4096 AND jsonb_typeof(billing_observation_json::jsonb)='object')),
 admitted_count INTEGER NOT NULL DEFAULT 0 CHECK(admitted_count>=0 AND official_used+admitted_count<=quota),
 account_block_code TEXT, account_block_until TEXT,
 text_block_code TEXT, text_block_until TEXT, detail_block_code TEXT, detail_block_until TEXT,
 PRIMARY KEY(account_scope,service_group,period)
);
CREATE TABLE public.amap_quota_attempts (
 id TEXT PRIMARY KEY CHECK(id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
 account_scope TEXT NOT NULL, service_group TEXT NOT NULL, period TEXT NOT NULL,
 endpoint TEXT NOT NULL CHECK(endpoint IN('text','detail')), admitted_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('reserved','succeeded','failed','unknown')),
 http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
 business_code TEXT CHECK(business_code ~ '^[0-9]{5}$'), completed_at TEXT,
 FOREIGN KEY(account_scope,service_group,period) REFERENCES public.amap_quota_buckets(account_scope,service_group,period)
);
CREATE INDEX idx_amap_quota_qps ON public.amap_quota_attempts(account_scope,service_group,period,endpoint,admitted_at);
CREATE FUNCTION public.noteai_amap_quota_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='amap_quota_buckets' THEN
   IF (to_jsonb(NEW)-ARRAY['admitted_count','account_block_code','account_block_until','text_block_code','text_block_until',
      'detail_block_code','detail_block_until','billing_observation_json']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['admitted_count','account_block_code','account_block_until','text_block_code','text_block_until',
      'detail_block_code','detail_block_until','billing_observation_json']) OR NEW.admitted_count<OLD.admitted_count THEN
     RAISE EXCEPTION 'amap baseline and cumulative admissions are immutable';
   END IF;
 ELSE
   IF (to_jsonb(NEW)-ARRAY['status','http_status','business_code','completed_at']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','http_status','business_code','completed_at']) OR OLD.status<>'reserved' OR NEW.status='reserved' THEN
     RAISE EXCEPTION 'amap attempt cannot be replayed or rewritten';
   END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.noteai_amap_quota_guard() FROM PUBLIC;
CREATE TRIGGER amap_quota_bucket_guard BEFORE UPDATE ON public.amap_quota_buckets
 FOR EACH ROW EXECUTE FUNCTION public.noteai_amap_quota_guard();
CREATE TRIGGER amap_quota_attempt_guard BEFORE UPDATE ON public.amap_quota_attempts
 FOR EACH ROW EXECUTE FUNCTION public.noteai_amap_quota_guard();
-- Owner defaults may grant future tables to other runtime roles. Remove grants
-- only from these just-created tables, without changing any existing table or
-- ALTER DEFAULT PRIVILEGES policy, before applying the explicit allowlist.
DO $$
DECLARE grant_row RECORD;
BEGIN
 FOR grant_row IN
   SELECT DISTINCT c.relname,a.grantee
   FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
   CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
   WHERE n.nspname='public' AND c.relname IN('amap_quota_buckets','amap_quota_attempts')
     AND a.grantee<>c.relowner
 LOOP
   EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %s',grant_row.relname,
     CASE WHEN grant_row.grantee=0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(grant_row.grantee)) END);
 END LOOP;
END $$;
GRANT SELECT ON public.amap_quota_buckets,public.amap_quota_attempts TO noteai_app,noteai_admin_runtime;
GRANT UPDATE(admitted_count,account_block_code,account_block_until,text_block_code,text_block_until,
 detail_block_code,detail_block_until) ON public.amap_quota_buckets TO noteai_app;
GRANT INSERT(id,account_scope,service_group,period,endpoint,admitted_at,status) ON public.amap_quota_attempts TO noteai_app;
GRANT UPDATE(status,http_status,business_code,completed_at) ON public.amap_quota_attempts TO noteai_app;
