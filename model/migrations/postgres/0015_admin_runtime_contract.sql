SET LOCAL TIME ZONE 'UTC';

-- Repository schema contract only. Role creation, credentials and ACL changes
-- are deliberately kept in the separately reviewed operator script.

ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS noteai_admin_sessions_runtime_v1 ON admin_sessions;
CREATE POLICY noteai_admin_sessions_runtime_v1 ON admin_sessions
FOR ALL TO PUBLIC
USING (current_user IN ('noteai_app','noteai_admin'))
WITH CHECK (current_user IN ('noteai_app','noteai_admin'));

DROP POLICY IF EXISTS noteai_system_settings_app_v1 ON system_settings;
CREATE POLICY noteai_system_settings_app_v1 ON system_settings
FOR ALL TO PUBLIC
USING (current_user = 'noteai_app')
WITH CHECK (current_user = 'noteai_app');

DROP POLICY IF EXISTS noteai_system_settings_admin_read_v1
    ON system_settings;
CREATE POLICY noteai_system_settings_admin_read_v1
    ON system_settings
FOR SELECT TO PUBLIC
USING (
    current_user = 'noteai_admin'
    AND is_secret = 0
    AND key IN ('model_registry','crawler_config')
);

DROP POLICY IF EXISTS noteai_ai_outbox_admin_read_v1
    ON ai_operation_outbox;
CREATE POLICY noteai_ai_outbox_admin_read_v1
    ON ai_operation_outbox
FOR SELECT TO PUBLIC
USING (current_user = 'noteai_admin');

DROP POLICY IF EXISTS noteai_ai_settlement_select_v1
    ON ai_operation_settlements;
CREATE POLICY noteai_ai_settlement_select_v1
    ON ai_operation_settlements
FOR SELECT TO PUBLIC
USING (
    current_user IN ('noteai_app','noteai_ai_worker','noteai_admin')
);
