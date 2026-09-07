-- Incremental runtime ACL for migration 0018.
--
-- Existing production receives the same grant conditionally inside 0018.
-- Fresh databases apply this file after the immutable 0009-0016 base ACL has
-- created the runtime roles. No LOGIN, password, membership or ownership is
-- changed here.

GRANT UPDATE(provider_submitted_at)
    ON payment_refunds TO noteai_payment;

GRANT UPDATE(duplicate_delivery_count)
    ON payment_events TO noteai_payment;
