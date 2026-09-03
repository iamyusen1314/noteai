SET LOCAL TIME ZONE 'UTC';

-- The managed RDS administrator already owns the noteai_admin login name.
-- Keep that control-plane identity outside the application runtime contract
-- and bind every Admin RLS allowance to the dedicated least-privilege role.

ALTER POLICY noteai_payment_orders_read_v1 ON payment_orders
USING (
    current_user IN ('noteai_app','noteai_payment','noteai_admin_runtime')
);

ALTER POLICY noteai_payment_refunds_read_v1 ON payment_refunds
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_events_read_v1 ON payment_events
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_cash_read_v1 ON payment_cash_ledger
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_entitlement_read_v1 ON payment_entitlement_ledger
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_positions_read_v1 ON payment_credit_positions
USING (
    current_user IN (
        'noteai_app','noteai_payment','noteai_admin_runtime','noteai_ai_worker'
    )
);

ALTER POLICY noteai_payment_consumptions_read_v1
    ON payment_credit_consumptions
USING (
    current_user IN (
        'noteai_app','noteai_payment','noteai_admin_runtime','noteai_ai_worker'
    )
);

ALTER POLICY noteai_payment_reconciliation_runs_read_v1
    ON payment_reconciliation_runs
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_reconciliation_items_read_v1
    ON payment_reconciliation_items
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_payment_settlements_read_v1
    ON payment_settlement_summaries
USING (current_user IN ('noteai_payment','noteai_admin_runtime'));

ALTER POLICY noteai_admin_sessions_runtime_v1 ON admin_sessions
USING (current_user IN ('noteai_app','noteai_admin_runtime'))
WITH CHECK (current_user IN ('noteai_app','noteai_admin_runtime'));

ALTER POLICY noteai_system_settings_admin_read_v1 ON system_settings
USING (
    current_user = 'noteai_admin_runtime'
    AND is_secret = 0
    AND key IN ('model_registry','crawler_config')
);

ALTER POLICY noteai_ai_outbox_admin_read_v1 ON ai_operation_outbox
USING (current_user = 'noteai_admin_runtime');

ALTER POLICY noteai_ai_settlement_select_v1 ON ai_operation_settlements
USING (
    current_user IN (
        'noteai_app','noteai_ai_worker','noteai_admin_runtime'
    )
);
