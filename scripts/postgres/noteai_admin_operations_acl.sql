-- Increment only the approved Admin operations; never replay the global roles script.
BEGIN;
DO $contract$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='noteai_admin_runtime'
        AND rolcanlogin AND NOT (rolsuper OR rolinherit OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
       OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='noteai_admin_runtime')
    THEN RAISE EXCEPTION 'dedicated Admin runtime role contract mismatch'; END IF;
END $contract$;

GRANT SELECT(deletion_requested_at) ON users TO noteai_admin_runtime;
GRANT EXECUTE ON FUNCTION public.noteai_admin_lock_user(TEXT), public.noteai_admin_lock_task(TEXT) TO noteai_admin_runtime;
GRANT SELECT,INSERT ON admin_operations TO noteai_admin_runtime;
GRANT UPDATE(tier,expires_at,entitlement_source,feature_overrides_json) ON subscriptions TO noteai_admin_runtime;
GRANT INSERT(user_id,balance,updated_at),UPDATE(balance,updated_at) ON credits TO noteai_admin_runtime;
GRANT INSERT(id,user_id,type,amount,balance_after,description,recorded_at) ON credit_transactions TO noteai_admin_runtime;
GRANT INSERT(key,label,module,content,version,updated_at),UPDATE(content,version,updated_at) ON managed_prompts TO noteai_admin_runtime;
GRANT INSERT(prompt_key,version,content,saved_at) ON prompt_history TO noteai_admin_runtime;
GRANT USAGE ON SEQUENCE prompt_history_id_seq TO noteai_admin_runtime;
GRANT INSERT(key,value_json,is_secret,updated_at),UPDATE(value_json,updated_at) ON system_settings TO noteai_admin_runtime;

GRANT UPDATE(operator_paused,priority,available_at,updated_at) ON ai_operations TO noteai_admin_runtime;
GRANT UPDATE(state,available_at,lease_owner_hash,lease_expires_at,delivered_at,updated_at) ON ai_operation_outbox TO noteai_admin_runtime;
GRANT SELECT(operation_id,idempotency_request_id) ON ai_operation_admissions TO noteai_admin_runtime;
-- Join existing usage rows to their business status; no task payload access.
GRANT SELECT(id,user_id,usage_id,operation,status,refund_applied,complete_applied) ON idempotency_requests TO noteai_admin_runtime;
GRANT SELECT(operation_id) ON ai_provider_attempts TO noteai_admin_runtime;
GRANT SELECT(id,operation_id,subject_hash,purpose,state,expires_at) ON ai_payload_refs TO noteai_admin_runtime;
GRANT SELECT(operator_paused) ON ai_operations TO noteai_ai_dispatcher;
-- Admission inserts new ordinary jobs; the scope cannot be changed afterwards.
GRANT INSERT(admin_control_scope) ON ai_operations TO noteai_app;
COMMIT;
