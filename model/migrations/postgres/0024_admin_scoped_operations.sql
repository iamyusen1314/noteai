-- Additive Admin operating state. No customer, payment, model or task mutation.
CREATE TABLE IF NOT EXISTS admin_operations (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    reason TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_operations_target
    ON admin_operations(target,created_at DESC);
ALTER TABLE admin_operations ENABLE ROW LEVEL SECURITY;
CREATE POLICY noteai_admin_operations_read ON admin_operations FOR SELECT
    USING (current_user='noteai_admin_runtime');
CREATE POLICY noteai_admin_operations_insert ON admin_operations FOR INSERT
    WITH CHECK (current_user='noteai_admin_runtime');

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS feature_overrides_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS entitlement_source TEXT NOT NULL DEFAULT 'existing';

ALTER TABLE ai_operations ADD COLUMN IF NOT EXISTS operator_paused INTEGER NOT NULL DEFAULT 0 CHECK (operator_paused IN (0,1));
-- Legacy/acceptance objects remain protected. Only the normal API admission
-- explicitly marks its new business jobs ordinary; no old identity is relabelled.
ALTER TABLE ai_operations ADD COLUMN IF NOT EXISTS admin_control_scope TEXT NOT NULL DEFAULT 'protected' CHECK (admin_control_scope IN ('protected','ordinary'));

CREATE FUNCTION public.noteai_admin_task_update_guard() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog AS $function$
BEGIN
    IF current_user IN ('noteai_admin_runtime','noteai_app','noteai_ai_worker','noteai_ai_dispatcher')
       AND NEW.admin_control_scope IS DISTINCT FROM OLD.admin_control_scope THEN
        RAISE EXCEPTION 'task management scope is immutable for runtime roles';
    END IF;
    IF current_user='noteai_admin_runtime' THEN
      IF NOT (
        OLD.admin_control_scope='ordinary' AND OLD.status='queued'
        AND OLD.provider_phase='not_started' AND OLD.provider_attempt_count=0
        AND (OLD.lease_expires_at IS NULL OR OLD.lease_expires_at::timestamptz<=clock_timestamp())
        AND NOT EXISTS (SELECT 1 FROM public.ai_provider_attempts p WHERE p.operation_id=OLD.id)
    ) THEN
        RAISE EXCEPTION 'protected or started task cannot be modified by Admin';
      END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.noteai_admin_task_update_guard() FROM PUBLIC;
CREATE TRIGGER noteai_admin_task_update_guard BEFORE UPDATE ON ai_operations
FOR EACH ROW EXECUTE FUNCTION public.noteai_admin_task_update_guard();

-- Narrow lock-only helpers: never expose or change identity/settlement fields.
CREATE FUNCTION public.noteai_admin_lock_user(target_user TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $function$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('noteai:user-write:' || target_user));
    PERFORM id FROM public.users WHERE id=target_user FOR UPDATE;
END
$function$;
REVOKE ALL ON FUNCTION public.noteai_admin_lock_user(TEXT) FROM PUBLIC;

CREATE FUNCTION public.noteai_admin_lock_task(target_operation TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $function$
DECLARE target_user TEXT;
BEGIN
    SELECT i.user_id INTO target_user FROM public.ai_operation_admissions a
    JOIN public.idempotency_requests i ON i.id=a.idempotency_request_id
    WHERE a.operation_id=target_operation;
    IF target_user IS NOT NULL THEN
        PERFORM public.noteai_admin_lock_user(target_user);
    END IF;
    PERFORM id FROM public.ai_operations WHERE id=target_operation FOR UPDATE;
    PERFORM id FROM public.ai_operation_outbox WHERE operation_id=target_operation FOR UPDATE;
    PERFORM operation_id FROM public.ai_operation_settlements WHERE operation_id=target_operation FOR UPDATE;
END
$function$;
REVOKE ALL ON FUNCTION public.noteai_admin_lock_task(TEXT) FROM PUBLIC;

-- Exact nonsecret settings only; no delete policy or arbitrary key namespace.
CREATE POLICY noteai_admin_operating_settings_read ON system_settings FOR SELECT
USING (current_user='noteai_admin_runtime' AND is_secret=0 AND key IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'));
CREATE POLICY noteai_admin_operating_settings_insert ON system_settings FOR INSERT
WITH CHECK (current_user='noteai_admin_runtime' AND is_secret=0 AND key IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'));
CREATE POLICY noteai_admin_operating_settings_update ON system_settings FOR UPDATE
USING (current_user='noteai_admin_runtime' AND is_secret=0 AND key IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'))
WITH CHECK (current_user='noteai_admin_runtime' AND is_secret=0 AND key IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'));

-- API reads published model config; it cannot publish an Admin draft. Preserve
-- its pre-existing access to all other settings and the frozen Tracking policy.
ALTER POLICY noteai_system_settings_app_v1 ON system_settings
USING (current_user='noteai_app' AND key NOT IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'))
WITH CHECK (current_user='noteai_app' AND key NOT IN ('admin_model_config','admin_model_config_test','admin_prompt_draft:agent_arbitrate_system','admin_prompt_draft:agent_content_system','admin_prompt_draft:agent_growth_system','admin_prompt_draft:agent_user_system','admin_prompt_draft:agent_visual_system','admin_prompt_draft:chat_system','admin_prompt_draft:gent_arbitrate_system','admin_prompt_draft:gent_content_system','admin_prompt_draft:gent_growth_system','admin_prompt_draft:gent_user_system','admin_prompt_draft:gent_visual_system','admin_prompt_draft:semantic_features'));
CREATE POLICY noteai_model_config_api_read ON system_settings FOR SELECT
USING (current_user='noteai_app' AND is_secret=0 AND key IN ('admin_model_config','admin_model_config_test'));

CREATE POLICY noteai_admin_task_ref_read ON ai_payload_refs FOR SELECT
USING (current_user='noteai_admin_runtime' AND purpose='request');
CREATE POLICY noteai_admin_task_outbox_update ON ai_operation_outbox FOR UPDATE TO noteai_admin_runtime
USING (current_user='noteai_admin_runtime' AND state IN ('pending','delivered')
       AND EXISTS (SELECT 1 FROM ai_operations o WHERE o.id=operation_id
                   AND o.admin_control_scope='ordinary' AND o.provider_phase='not_started'
                   AND o.provider_attempt_count=0 AND o.status IN ('queued','running')))
WITH CHECK (current_user='noteai_admin_runtime' AND state IN ('pending','delivered')
       AND EXISTS (SELECT 1 FROM ai_operations o WHERE o.id=operation_id
                   AND o.admin_control_scope='ordinary' AND o.provider_phase='not_started'
                   AND o.provider_attempt_count=0 AND o.status IN ('queued','running')));
