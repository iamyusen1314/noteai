-- Feature increment on the verified schema31 baseline. Never run the full
-- PostgreSQL migrator for this file; the integration owner owns exact inclusion.
BEGIN;
CREATE TABLE IF NOT EXISTS cover_jobs (
    id TEXT PRIMARY KEY REFERENCES idempotency_requests(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL CHECK(report_type IN ('generate','analyze')),
    report_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    budget_id TEXT NOT NULL REFERENCES public_trial_budget(id),
    usage_id TEXT NOT NULL UNIQUE REFERENCES usage_records(id) ON DELETE CASCADE,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    input_json TEXT NOT NULL,
    source_manifest_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    quote_version TEXT NOT NULL,
    call_intents_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('queued','running','saving','completed','failed','outcome_unknown')),
    stage TEXT NOT NULL,
    lease_token_hash TEXT,
    lease_fence INTEGER NOT NULL DEFAULT 0 CHECK(lease_fence>=0),
    lease_expires_at TEXT,
    deadline_at TEXT NOT NULL,
    unknown_at TEXT,
    final_media_ref TEXT REFERENCES private_media_refs(id),
    base_media_ref TEXT REFERENCES private_media_refs(id),
    layout_json TEXT,
    design_json TEXT,
    qc_json TEXT,
    asset_revision INTEGER NOT NULL DEFAULT 0 CHECK(asset_revision>=0),
    expires_at TEXT,
    failure_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK(status<>'completed' OR (final_media_ref IS NOT NULL AND base_media_ref IS NOT NULL
        AND layout_json IS NOT NULL AND qc_json IS NOT NULL AND asset_revision>0 AND expires_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_cover_jobs_report ON cover_jobs(user_id,report_type,report_id,created_at);
CREATE INDEX IF NOT EXISTS idx_cover_jobs_recovery ON cover_jobs(status,deadline_at,lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_cover_jobs_queue_user ON cover_jobs(user_id,status,created_at,id);

CREATE TABLE IF NOT EXISTS cover_image_usage (
    id TEXT PRIMARY KEY REFERENCES public_trial_calls(id),
    job_id TEXT NOT NULL REFERENCES cover_jobs(id) ON DELETE CASCADE,
    usage_id TEXT NOT NULL REFERENCES usage_records(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('dispatched','responded','failed','unknown')),
    input_images INTEGER NOT NULL CHECK(input_images BETWEEN 1 AND 9),
    output_images INTEGER NOT NULL DEFAULT 0 CHECK(output_images BETWEEN 0 AND 1),
    billed_images INTEGER CHECK(billed_images BETWEEN 0 AND 1),
    width INTEGER NOT NULL CHECK(width>0),
    height INTEGER NOT NULL CHECK(height>0),
    pricing_json TEXT NOT NULL,
    estimated_cost TEXT NOT NULL,
    actual_cost TEXT,
    currency TEXT NOT NULL,
    price_version TEXT NOT NULL,
    cost_status TEXT NOT NULL CHECK(cost_status IN ('estimated','unknown','billed')),
    evidence_ref_hash TEXT,
    response_hash TEXT,
    http_status INTEGER,
    provider_request_id TEXT CHECK(provider_request_id IS NULL OR length(provider_request_id) BETWEEN 1 AND 160),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    cost_reconciled_at TEXT,
    CHECK((cost_status='billed' AND actual_cost IS NOT NULL AND evidence_ref_hash IS NOT NULL)
          OR (cost_status<>'billed' AND actual_cost IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cover_one_image_call ON cover_image_usage(job_id);
CREATE INDEX IF NOT EXISTS idx_cover_image_usage_parent ON cover_image_usage(usage_id);

CREATE TABLE IF NOT EXISTS cover_asset_revisions (
    job_id TEXT NOT NULL REFERENCES cover_jobs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision>0),
    media_ref TEXT NOT NULL REFERENCES private_media_refs(id),
    layout_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id,revision),
    UNIQUE(job_id,media_ref)
);

-- PostgreSQL-only integration tail. Local SQLite tests explicitly initialize
-- the already compatible current SQLite schema and the new budget row.
ALTER TABLE public.public_trial_budget DROP CONSTRAINT IF EXISTS public_trial_budget_id_check;
ALTER TABLE public.public_trial_budget DROP CONSTRAINT IF EXISTS public_trial_budget_limit_milli_cny_check;
ALTER TABLE public.public_trial_budget DROP CONSTRAINT IF EXISTS noteai_cover_budget_identity;
ALTER TABLE public.public_trial_budget ADD CONSTRAINT noteai_cover_budget_identity CHECK (
    (id='website-free-product-20260912' AND limit_milli_cny=50000) OR
    (id='noteai-xhs-cover-20261019-acceptance' AND limit_milli_cny=100000) OR
    (id='noteai-cover-formal-v1' AND limit_milli_cny=0 AND policy_mode='owner_metered'));
INSERT INTO public.public_trial_budget(id,limit_milli_cny,reserved_milli_cny,enabled,policy_mode)
    VALUES('noteai-xhs-cover-20261019-acceptance',100000,0,1,'owner_metered')
    ON CONFLICT(id) DO NOTHING;
-- Formal is a separate inactive-feature accounting scope, not a test budget.
-- Creating this row does not enable the cover configuration or worker.
INSERT INTO public.public_trial_budget(id,limit_milli_cny,reserved_milli_cny,enabled,policy_mode)
    VALUES('noteai-cover-formal-v1',0,0,1,'owner_metered') ON CONFLICT(id) DO NOTHING;
REVOKE ALL ON cover_jobs,cover_image_usage,cover_asset_revisions FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON cover_jobs,cover_image_usage TO noteai_app;
GRANT SELECT,INSERT ON cover_asset_revisions TO noteai_app;
GRANT SELECT(status) ON cover_jobs TO noteai_admin_runtime;
GRANT SELECT(provider,model_id,state,input_images,output_images,billed_images,width,height,
    estimated_cost,actual_cost,currency,price_version,cost_status,created_at,completed_at,cost_reconciled_at)
    ON cover_image_usage TO noteai_admin_runtime;

-- Extend the existing schema31 nonsecret Admin contract for exactly two keys.
-- The API can read these published settings; it cannot write or delete them.
DROP POLICY IF EXISTS noteai_cover_config_admin_read ON public.system_settings;
CREATE POLICY noteai_cover_config_admin_read ON public.system_settings FOR SELECT
    TO noteai_admin_runtime USING (current_user='noteai_admin_runtime' AND is_secret=0
        AND key IN ('noteai_cover_config_v1','noteai_cover_config_v1_test'));
DROP POLICY IF EXISTS noteai_cover_config_admin_insert ON public.system_settings;
CREATE POLICY noteai_cover_config_admin_insert ON public.system_settings FOR INSERT
    TO noteai_admin_runtime WITH CHECK (current_user='noteai_admin_runtime' AND is_secret=0
        AND key IN ('noteai_cover_config_v1','noteai_cover_config_v1_test'));
DROP POLICY IF EXISTS noteai_cover_config_admin_update ON public.system_settings;
CREATE POLICY noteai_cover_config_admin_update ON public.system_settings FOR UPDATE
    TO noteai_admin_runtime USING (current_user='noteai_admin_runtime' AND is_secret=0
        AND key IN ('noteai_cover_config_v1','noteai_cover_config_v1_test'))
    WITH CHECK (current_user='noteai_admin_runtime' AND is_secret=0
        AND key IN ('noteai_cover_config_v1','noteai_cover_config_v1_test'));
ALTER POLICY noteai_system_settings_app_v1 ON public.system_settings
USING (current_user='noteai_app' AND key NOT IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features','noteai_cover_config_v1','noteai_cover_config_v1_test'))
WITH CHECK (current_user='noteai_app' AND key NOT IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features','noteai_cover_config_v1','noteai_cover_config_v1_test'));
DROP POLICY IF EXISTS noteai_cover_config_api_read ON public.system_settings;
CREATE POLICY noteai_cover_config_api_read ON public.system_settings FOR SELECT TO noteai_app
    USING (current_user='noteai_app' AND is_secret=0
        AND key IN ('noteai_cover_config_v1','noteai_cover_config_v1_test'));
COMMIT;
