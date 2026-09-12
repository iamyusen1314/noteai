-- Preserve all historical deliveries and the existing cumulative SMS budget.
-- This only permits the actual PNVS provider identity for future deliveries.
ALTER TABLE public.auth_sms_deliveries
    DROP CONSTRAINT auth_sms_deliveries_provider_check;
ALTER TABLE public.auth_sms_deliveries
    ADD CONSTRAINT auth_sms_deliveries_provider_check
    CHECK (provider IN ('aliyun_sms','aliyun_pnvs'));
