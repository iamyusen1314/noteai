SET LOCAL TIME ZONE 'UTC';

-- PostgreSQL remains authoritative. NOTIFY carries only a canonical UUID and
-- is a bounded-latency wake hint; workers always re-check delivered rows.

CREATE INDEX IF NOT EXISTS idx_ai_operation_outbox_delivered_claim
    ON ai_operation_outbox(delivered_at, id)
    INCLUDE (operation_id)
    WHERE state = 'delivered';

DROP POLICY IF EXISTS noteai_ai_outbox_worker_delivered_v1
    ON ai_operation_outbox;
CREATE POLICY noteai_ai_outbox_worker_delivered_v1
    ON ai_operation_outbox
    FOR SELECT TO PUBLIC
    USING (
        current_user = 'noteai_ai_worker'
        AND state = 'delivered'
    );

-- Existing production already has the inert runtime roles. Fresh databases
-- apply migrations before those roles are created, then receive the same
-- grants from noteai_production_runtime_roles.sql.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'noteai_ai_worker'
    ) THEN
        EXECUTE 'GRANT SELECT(id, operation_id, state, delivered_at) '
                'ON ai_operation_outbox TO noteai_ai_worker';
        EXECUTE 'GRANT SELECT(id, user_id, period_start, used_monthly_credits) '
                'ON subscriptions TO noteai_ai_worker';
        EXECUTE 'GRANT SELECT(user_id, balance, total_used) '
                'ON credits TO noteai_ai_worker';
        EXECUTE 'GRANT SELECT(id, user_id) '
                'ON usage_records TO noteai_ai_worker';
    END IF;
END
$$;
