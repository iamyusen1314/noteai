-- Item31 preparation: admit the two owner-selected direct providers while
-- retaining every accepted Adapay row. This migration performs no payment,
-- credential, login, membership, ownership, entitlement or balance action.
ALTER TABLE payment_orders
    DROP CONSTRAINT payment_orders_provider_check,
    ADD CONSTRAINT payment_orders_provider_check
        CHECK (provider IN ('adapay','wechatpay_direct','alipay_direct'));

ALTER TABLE payment_reconciliation_runs
    DROP CONSTRAINT payment_reconciliation_runs_provider_check,
    ADD CONSTRAINT payment_reconciliation_runs_provider_check
        CHECK (provider IN ('adapay','wechatpay_direct','alipay_direct'));

ALTER TABLE payment_settlement_summaries
    DROP CONSTRAINT payment_settlement_summaries_provider_check,
    ADD CONSTRAINT payment_settlement_summaries_provider_check
        CHECK (provider IN ('adapay','wechatpay_direct','alipay_direct'));

-- Preserve the authenticated WeChat response body's create_time for the one
-- refund submission. WeChat trade bills assign refunds to their successful
-- initiation day rather than to a later terminal callback/query day.
ALTER TABLE payment_refunds
    ADD COLUMN provider_submitted_at BIGINT
        CHECK (
            provider_submitted_at IS NULL
            OR provider_submitted_at BETWEEN 946684800 AND 4102444800
        );

ALTER TABLE payment_events
    ADD COLUMN duplicate_delivery_count BIGINT NOT NULL DEFAULT 0
        CHECK (duplicate_delivery_count BETWEEN 0 AND 1000000);

CREATE OR REPLACE FUNCTION noteai_payment_event_identity_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.provider_event_id_hash <> OLD.provider_event_id_hash
       OR NEW.event_type <> OLD.event_type
       OR NEW.payload_sha256 <> OLD.payload_sha256
       OR NEW.signature_sha256 <> OLD.signature_sha256
       OR NEW.app_id_hash <> OLD.app_id_hash
       OR NEW.prod_mode <> OLD.prod_mode
       OR NEW.provider_created_at <> OLD.provider_created_at
       OR NEW.received_at <> OLD.received_at THEN
        RAISE EXCEPTION 'payment event identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (OLD.processing_state <> 'accepted'
            AND NEW.processing_state <> OLD.processing_state)
       OR (OLD.processing_state = 'accepted'
            AND NEW.processing_state NOT IN (
                'accepted','processed','ignored','needs_manual'
            ))
       OR NEW.duplicate_delivery_count < OLD.duplicate_delivery_count
       OR NEW.duplicate_delivery_count > OLD.duplicate_delivery_count + 1 THEN
        RAISE EXCEPTION 'invalid payment event transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION noteai_payment_refund_identity_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.order_id <> OLD.order_id
       OR NEW.merchant_refund_no <> OLD.merchant_refund_no
       OR NEW.amount_fen <> OLD.amount_fen
       OR NEW.currency <> OLD.currency
       OR NEW.reason_code <> OLD.reason_code
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'payment refund identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (OLD.status = 'requested'
            AND NEW.status NOT IN (
                'requested','pending','succeeded','failed','needs_manual'
            ))
       OR (OLD.status = 'pending'
            AND NEW.status NOT IN (
                'pending','succeeded','failed','needs_manual'
            ))
       OR (OLD.status = 'succeeded' AND NEW.status <> 'succeeded')
       OR (OLD.status = 'failed'
            AND NEW.status NOT IN ('failed','needs_manual'))
       OR (OLD.status = 'needs_manual' AND NEW.status <> 'needs_manual')
       OR (
            OLD.provider_refund_id IS NOT NULL
            AND NEW.provider_refund_id IS DISTINCT FROM OLD.provider_refund_id
       )
       OR (
            OLD.provider_submitted_at IS NOT NULL
            AND NEW.provider_submitted_at
                IS DISTINCT FROM OLD.provider_submitted_at
       )
       OR (
            NEW.provider_submitted_at IS NOT NULL
            AND (
                NEW.status = 'requested'
                OR NOT EXISTS (
                    SELECT 1
                    FROM public.payment_orders
                    WHERE id = NEW.order_id
                      AND provider = 'wechatpay_direct'
                )
            )
       ) THEN
        RAISE EXCEPTION 'invalid payment refund transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION noteai_payment_refund_insert_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.provider_submitted_at IS NOT NULL
       OR NOT EXISTS (
            SELECT 1
            FROM public.payment_orders
            WHERE id = NEW.order_id
              AND amount_fen = NEW.amount_fen
              AND payment_status = 'succeeded'
              AND entitlement_status = 'applied'
              AND refunded_fen = 0
       ) THEN
        RAISE EXCEPTION 'invalid full refund intent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

-- Existing production already has the inert payment runtime role. Fresh
-- databases apply the matching incremental ACL after creating runtime roles.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'noteai_payment'
    ) THEN
        EXECUTE 'GRANT UPDATE(provider_submitted_at) '
                'ON payment_refunds TO noteai_payment';
        EXECUTE 'GRANT UPDATE(duplicate_delivery_count) '
                'ON payment_events TO noteai_payment';
    END IF;
END
$$;
