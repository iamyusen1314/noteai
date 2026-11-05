-- Per-account/model rolling rate counters only. Original physical calls,
-- UNKNOWN outcomes, supplier costs and customer credits remain untouched.
-- One bounded 61-second ring per verified model family; no runtime DELETE.
CREATE TABLE public.model_capacity_buckets (
 scope_key TEXT NOT NULL CHECK(length(scope_key) BETWEEN 1 AND 100),
 quota_key TEXT NOT NULL CHECK(length(quota_key) BETWEEN 1 AND 100),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 60),
 epoch_second BIGINT NOT NULL CHECK(epoch_second>=0 AND slot=epoch_second%61),
 request_count BIGINT NOT NULL CHECK(request_count>=0),
 token_bound BIGINT NOT NULL CHECK(token_bound>=0),
 image_count BIGINT NOT NULL CHECK(image_count>=0),
 input_bound BIGINT NOT NULL CHECK(input_bound>=0),
 output_bound BIGINT NOT NULL CHECK(output_bound>=0),
 CHECK(token_bound=input_bound+output_bound),
 PRIMARY KEY(scope_key,quota_key,slot)
);
-- Remove inherited defaults from this new table only, then grant the API's
-- minimum counter permissions. Admin/payment/worker roles gain no new access.
DO $$
DECLARE grant_row RECORD;
BEGIN
 FOR grant_row IN
   SELECT DISTINCT a.grantee
   FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
   CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
   WHERE n.nspname='public' AND c.relname='model_capacity_buckets' AND a.grantee<>c.relowner
 LOOP
   EXECUTE format('REVOKE ALL ON TABLE public.model_capacity_buckets FROM %s',
     CASE WHEN grant_row.grantee=0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(grant_row.grantee)) END);
 END LOOP;
END $$;
GRANT SELECT ON public.model_capacity_buckets TO noteai_app;
GRANT INSERT(scope_key,quota_key,slot,epoch_second,request_count,token_bound,image_count,input_bound,output_bound)
 ON public.model_capacity_buckets TO noteai_app;
GRANT UPDATE(epoch_second,request_count,token_bound,image_count,input_bound,output_bound)
 ON public.model_capacity_buckets TO noteai_app;
