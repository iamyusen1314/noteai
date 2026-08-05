-- Incremental runtime ACL for migration 0017.
--
-- Existing production receives the same grants conditionally inside 0017.
-- Fresh databases apply this file after the immutable 0009-0016 base ACL has
-- created the runtime roles. No LOGIN, password, membership or ownership is
-- changed here.

GRANT SELECT(id, operation_id, state, delivered_at)
    ON ai_operation_outbox TO noteai_ai_worker;
GRANT SELECT(id, user_id, period_start, used_monthly_credits)
    ON subscriptions TO noteai_ai_worker;
GRANT SELECT(user_id, balance, total_used)
    ON credits TO noteai_ai_worker;
GRANT SELECT(id, user_id)
    ON usage_records TO noteai_ai_worker;
