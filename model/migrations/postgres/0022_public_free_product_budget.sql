-- Separate website budget; neither an entitlement grant nor an Item34 mutation.
CREATE TABLE public.public_trial_budget (
    id TEXT PRIMARY KEY CHECK(id='website-free-product-20260912'),
    limit_milli_cny INTEGER NOT NULL CHECK(limit_milli_cny=50000),
    reserved_milli_cny INTEGER NOT NULL DEFAULT 0 CHECK(reserved_milli_cny BETWEEN 0 AND limit_milli_cny),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1))
);
INSERT INTO public.public_trial_budget(id,limit_milli_cny) VALUES('website-free-product-20260912',50000);
CREATE TABLE public.public_trial_calls (
    id TEXT PRIMARY KEY, budget_id TEXT NOT NULL REFERENCES public.public_trial_budget(id),
    user_id TEXT NOT NULL REFERENCES public.users(id), request_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN('dispatched','responded','unknown')),
    reserve_milli_cny INTEGER NOT NULL CHECK(reserve_milli_cny=2590),
    http_status INTEGER, created_at TEXT NOT NULL
);
CREATE INDEX idx_public_trial_request ON public.public_trial_calls(request_hash,state);
CREATE FUNCTION public.noteai_trial_budget_monotone() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.id<>OLD.id OR NEW.limit_milli_cny<>OLD.limit_milli_cny
       OR NEW.reserved_milli_cny<OLD.reserved_milli_cny THEN
        RAISE EXCEPTION 'Public trial cumulative budget cannot be reset';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.noteai_trial_budget_monotone() FROM PUBLIC;
CREATE TRIGGER trial_budget_monotone BEFORE UPDATE ON public.public_trial_budget
    FOR EACH ROW EXECUTE FUNCTION public.noteai_trial_budget_monotone();
REVOKE ALL ON public.public_trial_budget,public.public_trial_calls FROM PUBLIC,noteai_app;
GRANT SELECT ON public.public_trial_budget,public.public_trial_calls TO noteai_app;
GRANT UPDATE(reserved_milli_cny) ON public.public_trial_budget TO noteai_app;
GRANT INSERT ON public.public_trial_calls TO noteai_app;
GRANT UPDATE(state,http_status) ON public.public_trial_calls TO noteai_app;
