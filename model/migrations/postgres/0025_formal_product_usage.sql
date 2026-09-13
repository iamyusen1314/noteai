-- Owner September13: formal entitlements use metered quality, without the old
-- trial monetary stop. Keep all old amounts/calls; no inferred historical links.
ALTER TABLE public.public_trial_budget
    ADD COLUMN policy_mode TEXT NOT NULL DEFAULT 'legacy_capped'
    CHECK (policy_mode IN ('legacy_capped','owner_metered'));
ALTER TABLE public.public_trial_budget
    DROP CONSTRAINT public_trial_budget_check;
ALTER TABLE public.public_trial_budget
    ALTER COLUMN reserved_milli_cny TYPE BIGINT;
ALTER TABLE public.public_trial_budget ADD CONSTRAINT public_trial_reserve_policy
    CHECK (reserved_milli_cny>=0 AND
           (policy_mode='owner_metered' OR reserved_milli_cny<=limit_milli_cny));
ALTER TABLE public.public_trial_calls
    DROP CONSTRAINT public_trial_calls_reserve_milli_cny_check;
ALTER TABLE public.public_trial_calls ADD CONSTRAINT public_trial_call_reserve_nonnegative
    CHECK (reserve_milli_cny>=0);
ALTER TABLE public.public_trial_calls
    ADD COLUMN usage_record_id TEXT REFERENCES public.usage_records(id),
    ADD COLUMN model_usage_record_id TEXT UNIQUE REFERENCES public.model_usage_records(id),
    ADD COLUMN usage_fingerprint TEXT,
    ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (octet_length(provenance_json)<=16384);
ALTER TABLE public.public_trial_calls ADD CONSTRAINT public_trial_accounting_binding
    CHECK ((model_usage_record_id IS NULL AND usage_fingerprint IS NULL) OR
           (usage_record_id IS NOT NULL AND model_usage_record_id IS NOT NULL
            AND usage_fingerprint IS NOT NULL AND usage_fingerprint ~ '^[0-9a-f]{64}$'));
-- The application may finish only its original call's accounting link. It may
-- not change policy, principal, old reservations or manufacture linked history.
GRANT UPDATE(model_usage_record_id,usage_fingerprint) ON public.public_trial_calls TO noteai_app;
-- The Admin reads only content-free call provenance, not identities/request hashes.
GRANT SELECT(created_at,provenance_json) ON public.public_trial_calls TO noteai_admin_runtime;
UPDATE public.public_trial_budget SET policy_mode='owner_metered'
    WHERE id='website-free-product-20260912';
