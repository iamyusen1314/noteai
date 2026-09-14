-- Same original paid claim + existing private chat session (same server UUID).
-- No new queue, identity, money movement or content in the idempotency ledger.
ALTER TABLE idempotency_requests DROP CONSTRAINT idempotency_requests_status_check;
ALTER TABLE idempotency_requests ADD CONSTRAINT idempotency_requests_status_check
    CHECK (status IN ('running','waiting_for_input','completed','failed'));
ALTER TABLE idempotency_requests ADD CONSTRAINT idempotency_clarification_state_check
    CHECK (status <> 'waiting_for_input' OR (
        operation IN ('analyze','generate') AND usage_id IS NOT NULL
        AND usage_created=1 AND charge_applied=1
        AND complete_applied=0 AND refund_applied=0));
