-- Additive auth-only change. Never reset or refund cumulative reservations.
CREATE TABLE public.auth_sms_budget (
    id TEXT PRIMARY KEY CHECK (id = 'website-accounts-20260912'),
    limit_milli_cny INTEGER NOT NULL CHECK (limit_milli_cny BETWEEN 60 AND 60000),
    reserved_milli_cny INTEGER NOT NULL DEFAULT 0
        CHECK (reserved_milli_cny >= 0 AND reserved_milli_cny <= limit_milli_cny),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1))
);
INSERT INTO public.auth_sms_budget(id,limit_milli_cny)
    VALUES ('website-accounts-20260912',60000);

CREATE TABLE public.auth_sms_deliveries (
    challenge_id TEXT PRIMARY KEY REFERENCES public.auth_verification_challenges(id),
    budget_id TEXT NOT NULL REFERENCES public.auth_sms_budget(id),
    provider TEXT NOT NULL CHECK (provider = 'aliyun_sms'),
    state TEXT NOT NULL CHECK (state IN ('reserved','accepted','rejected','unknown')),
    reserve_milli_cny INTEGER NOT NULL CHECK (reserve_milli_cny = 60),
    provider_code TEXT NOT NULL DEFAULT '',
    provider_request_id TEXT NOT NULL DEFAULT '',
    provider_biz_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_auth_sms_delivery_created ON public.auth_sms_deliveries(created_at);
CREATE INDEX idx_auth_verification_contact_all_purposes
    ON public.auth_verification_challenges(destination_hash,created_at);
CREATE INDEX idx_auth_verification_source_all_purposes
    ON public.auth_verification_challenges(requester_hash,created_at)
    WHERE requester_hash <> '';

CREATE FUNCTION public.noteai_sms_budget_monotone() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.limit_milli_cny <> OLD.limit_milli_cny
       OR NEW.reserved_milli_cny < OLD.reserved_milli_cny THEN
        RAISE EXCEPTION 'SMS cumulative budget cannot be reset or enlarged';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.noteai_sms_budget_monotone() FROM PUBLIC;
CREATE TRIGGER sms_budget_monotone BEFORE UPDATE ON public.auth_sms_budget
    FOR EACH ROW EXECUTE FUNCTION public.noteai_sms_budget_monotone();

REVOKE ALL ON public.auth_sms_budget, public.auth_sms_deliveries FROM PUBLIC;
REVOKE ALL ON public.auth_sms_budget, public.auth_sms_deliveries FROM noteai_app;
GRANT SELECT ON public.auth_sms_budget, public.auth_sms_deliveries TO noteai_app;
GRANT UPDATE(reserved_milli_cny) ON public.auth_sms_budget TO noteai_app;
GRANT INSERT ON public.auth_sms_deliveries TO noteai_app;
GRANT UPDATE(state,provider_code,provider_request_id,provider_biz_id,updated_at)
    ON public.auth_sms_deliveries TO noteai_app;
-- The authorized deployment enables the fixed budget after platform configuration,
-- before the consented private test. Startup and migration never enable it.
