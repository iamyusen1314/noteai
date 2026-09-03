SET LOCAL TIME ZONE 'UTC';

-- Repository contract only. This migration intentionally contains no role,
-- GRANT, REVOKE, credential, provider call or service change. Money is CNY
-- integer fen; callback bodies, signatures and payer data are never stored.

CREATE TABLE IF NOT EXISTS payment_orders (
    id                   TEXT PRIMARY KEY
                         CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    user_id              TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_hash         TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    product_kind         TEXT NOT NULL
                         CHECK (product_kind IN ('subscription','credit_package')),
    product_id           TEXT NOT NULL,
    catalog_version      TEXT NOT NULL
                         CHECK (catalog_version = 'first-launch-v1-2026-07-26'),
    amount_fen           BIGINT NOT NULL CHECK (amount_fen BETWEEN 1 AND 100000000),
    currency             TEXT NOT NULL CHECK (currency = 'CNY'),
    provider             TEXT NOT NULL CHECK (provider = 'adapay'),
    provider_mode        TEXT NOT NULL CHECK (provider_mode IN ('mock','live')),
    merchant_order_no    TEXT NOT NULL UNIQUE
                         CHECK (merchant_order_no ~ '^[A-Za-z0-9_:-]{1,128}$'),
    provider_payment_id  TEXT UNIQUE
                         CHECK (
                             provider_payment_id IS NULL
                             OR provider_payment_id ~ '^[A-Za-z0-9_:-]{1,128}$'
                         ),
    app_id_hash          TEXT NOT NULL CHECK (app_id_hash ~ '^[0-9a-f]{64}$'),
    idempotency_key_hash TEXT NOT NULL
                         CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash         TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    payment_status       TEXT NOT NULL CHECK (
                             payment_status IN (
                                 'created','pending','succeeded','failed',
                                 'closed','needs_manual'
                             )
                         ),
    entitlement_status   TEXT NOT NULL CHECK (
                             entitlement_status IN (
                                 'pending','applied','reversed','needs_manual'
                             )
                         ),
    entitlement_ref      TEXT,
    refund_status        TEXT NOT NULL CHECK (
                             refund_status IN (
                                 'none','pending','refunded','needs_manual'
                             )
                         ),
    refunded_fen         BIGINT NOT NULL DEFAULT 0
                         CHECK (refunded_fen BETWEEN 0 AND amount_fen),
    refund_count         INTEGER NOT NULL DEFAULT 0
                         CHECK (refund_count BETWEEN 0 AND 1),
    created_at           TEXT NOT NULL CHECK (
                             created_at = btrim(created_at)
                             AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                             AND created_at::timestamptz IS NOT NULL
                         ),
    updated_at           TEXT NOT NULL CHECK (
                             updated_at = btrim(updated_at)
                             AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                             AND updated_at::timestamptz IS NOT NULL
                         ),
    succeeded_at         TEXT,
    terminal_at          TEXT,
    UNIQUE(user_id,idempotency_key_hash),
    CHECK (
        (product_kind = 'subscription'
            AND (
                (product_id = 'pro' AND amount_fen = 9900)
                OR (product_id = 'growth' AND amount_fen = 19900)
                OR (product_id = 'pro_plus' AND amount_fen = 29900)
                OR (product_id = 'studio' AND amount_fen = 39900)
            ))
        OR
        (product_kind = 'credit_package'
            AND (
                (product_id = 'starter' AND amount_fen = 1200)
                OR (product_id = 'creator' AND amount_fen = 3900)
                OR (product_id = 'growth' AND amount_fen = 10900)
                OR (product_id = 'studio' AND amount_fen = 27900)
            ))
    ),
    CHECK (entitlement_status = 'pending' OR payment_status = 'succeeded'),
    CHECK (created_at::timestamptz <= updated_at::timestamptz),
    CHECK (
        succeeded_at IS NULL
        OR (
            succeeded_at = btrim(succeeded_at)
            AND succeeded_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
            AND succeeded_at::timestamptz >= created_at::timestamptz
        )
    ),
    CHECK (
        terminal_at IS NULL
        OR (
            terminal_at = btrim(terminal_at)
            AND terminal_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
            AND terminal_at::timestamptz >= created_at::timestamptz
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_orders_user
    ON payment_orders(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_orders_state
    ON payment_orders(payment_status,entitlement_status,updated_at);

CREATE TABLE IF NOT EXISTS payment_refunds (
    id                   TEXT PRIMARY KEY
                         CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    order_id             TEXT NOT NULL REFERENCES payment_orders(id) ON DELETE RESTRICT,
    merchant_refund_no   TEXT NOT NULL UNIQUE
                         CHECK (merchant_refund_no ~ '^[A-Za-z0-9_:-]{1,128}$'),
    provider_refund_id   TEXT UNIQUE
                         CHECK (
                             provider_refund_id IS NULL
                             OR provider_refund_id ~ '^[A-Za-z0-9_:-]{1,128}$'
                         ),
    amount_fen           BIGINT NOT NULL CHECK (amount_fen BETWEEN 1 AND 100000000),
    currency             TEXT NOT NULL CHECK (currency = 'CNY'),
    status               TEXT NOT NULL CHECK (
                             status IN (
                                 'requested','pending','succeeded','failed','needs_manual'
                             )
                         ),
    reason_code          TEXT NOT NULL CHECK (
                             reason_code IN (
                                 'customer_request','service_not_delivered',
                                 'duplicate_payment','fraud_review'
                             )
                         ),
    created_at           TEXT NOT NULL CHECK (
                             created_at = btrim(created_at)
                             AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                             AND created_at::timestamptz IS NOT NULL
                         ),
    updated_at           TEXT NOT NULL CHECK (
                             updated_at = btrim(updated_at)
                             AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                             AND updated_at::timestamptz IS NOT NULL
                         ),
    terminal_at          TEXT,
    CHECK (created_at::timestamptz <= updated_at::timestamptz),
    CHECK (
        terminal_at IS NULL
        OR (
            terminal_at = btrim(terminal_at)
            AND terminal_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
            AND terminal_at::timestamptz >= created_at::timestamptz
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_refunds_order
    ON payment_refunds(order_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_refunds_one_v1
    ON payment_refunds(order_id);

CREATE TABLE IF NOT EXISTS payment_events (
    id                       TEXT PRIMARY KEY
                             CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    provider_event_id_hash   TEXT NOT NULL UNIQUE
                             CHECK (provider_event_id_hash ~ '^[0-9a-f]{64}$'),
    event_type               TEXT NOT NULL CHECK (char_length(event_type) BETWEEN 3 AND 64),
    payload_sha256           TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    signature_sha256         TEXT NOT NULL CHECK (signature_sha256 ~ '^[0-9a-f]{64}$'),
    app_id_hash              TEXT NOT NULL CHECK (app_id_hash ~ '^[0-9a-f]{64}$'),
    prod_mode                INTEGER NOT NULL CHECK (prod_mode IN (0,1)),
    provider_created_at      BIGINT NOT NULL
                             CHECK (provider_created_at BETWEEN 946684800 AND 4102444800),
    processing_state         TEXT NOT NULL CHECK (
                                 processing_state IN (
                                     'accepted','processed','ignored','needs_manual'
                                 )
                             ),
    reason_code              TEXT NOT NULL,
    order_id                 TEXT REFERENCES payment_orders(id) ON DELETE RESTRICT,
    refund_id                TEXT REFERENCES payment_refunds(id) ON DELETE RESTRICT,
    received_at              TEXT NOT NULL CHECK (
                                 received_at = btrim(received_at)
                                 AND received_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                                 AND received_at::timestamptz IS NOT NULL
                             ),
    processed_at             TEXT,
    CHECK (
        processed_at IS NULL
        OR (
            processed_at = btrim(processed_at)
            AND processed_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
            AND processed_at::timestamptz >= received_at::timestamptz
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_events_state
    ON payment_events(processing_state,received_at);

CREATE TABLE IF NOT EXISTS payment_cash_ledger (
    id               TEXT PRIMARY KEY
                     CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    order_id         TEXT NOT NULL REFERENCES payment_orders(id) ON DELETE RESTRICT,
    refund_id        TEXT REFERENCES payment_refunds(id) ON DELETE RESTRICT,
    entry_type       TEXT NOT NULL CHECK (
                         entry_type IN (
                             'payment_received','payment_received_unmatched',
                             'refund_paid','refund_paid_unmatched'
                         )
                     ),
    amount_fen       BIGINT NOT NULL CHECK (
                         amount_fen BETWEEN -100000000 AND 100000000
                         AND amount_fen <> 0
                     ),
    currency         TEXT NOT NULL CHECK (currency = 'CNY'),
    source_event_id  TEXT NOT NULL UNIQUE
                     REFERENCES payment_events(id) ON DELETE RESTRICT,
    recorded_at      TEXT NOT NULL CHECK (
                         recorded_at = btrim(recorded_at)
                         AND recorded_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                         AND recorded_at::timestamptz IS NOT NULL
                     ),
    CHECK (
        (entry_type LIKE 'payment\_%' ESCAPE '\' AND amount_fen > 0
            AND refund_id IS NULL)
        OR
        (entry_type LIKE 'refund\_%' ESCAPE '\' AND amount_fen < 0
            AND refund_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_cash_recorded
    ON payment_cash_ledger(recorded_at,entry_type);
CREATE INDEX IF NOT EXISTS idx_payment_cash_order
    ON payment_cash_ledger(order_id,recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_cash_one_receipt_v1
    ON payment_cash_ledger(order_id)
    WHERE entry_type IN ('payment_received','payment_received_unmatched');
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_cash_one_refund_v1
    ON payment_cash_ledger(refund_id)
    WHERE entry_type IN ('refund_paid','refund_paid_unmatched');

CREATE TABLE IF NOT EXISTS payment_entitlement_ledger (
    id                TEXT PRIMARY KEY
                      CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    order_id          TEXT NOT NULL REFERENCES payment_orders(id) ON DELETE RESTRICT,
    refund_id         TEXT REFERENCES payment_refunds(id) ON DELETE RESTRICT,
    entry_type        TEXT NOT NULL CHECK (
                          entry_type IN (
                              'credit_grant','credit_reversal',
                              'subscription_grant','subscription_reversal'
                          )
                      ),
    product_kind      TEXT NOT NULL
                      CHECK (product_kind IN ('subscription','credit_package')),
    product_id        TEXT NOT NULL,
    quantity_milli    BIGINT NOT NULL CHECK (quantity_milli <> 0),
    subscription_id   TEXT,
    source_event_id   TEXT NOT NULL UNIQUE
                      REFERENCES payment_events(id) ON DELETE RESTRICT,
    recorded_at       TEXT NOT NULL CHECK (
                          recorded_at = btrim(recorded_at)
                          AND recorded_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                          AND recorded_at::timestamptz IS NOT NULL
                      ),
    CHECK (
        (entry_type LIKE '%\_grant' ESCAPE '\' AND quantity_milli > 0
            AND refund_id IS NULL)
        OR
        (entry_type LIKE '%\_reversal' ESCAPE '\' AND quantity_milli < 0
            AND refund_id IS NOT NULL)
    ),
    CHECK (
        (product_kind = 'subscription' AND subscription_id IS NOT NULL)
        OR
        (product_kind = 'credit_package' AND subscription_id IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_entitlement_order
    ON payment_entitlement_ledger(order_id,recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_entitlement_once_v1
    ON payment_entitlement_ledger(order_id,entry_type);

CREATE TABLE IF NOT EXISTS payment_credit_positions (
    order_id         TEXT PRIMARY KEY REFERENCES payment_orders(id) ON DELETE RESTRICT,
    user_id          TEXT REFERENCES users(id) ON DELETE SET NULL,
    subject_hash     TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    granted_milli    BIGINT NOT NULL CHECK (granted_milli > 0),
    remaining_milli  BIGINT NOT NULL
                     CHECK (remaining_milli BETWEEN 0 AND granted_milli),
    state            TEXT NOT NULL CHECK (state IN ('active','consumed','reversed')),
    created_at       TEXT NOT NULL CHECK (
                         created_at = btrim(created_at)
                         AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                         AND created_at::timestamptz IS NOT NULL
                     ),
    updated_at       TEXT NOT NULL CHECK (
                         updated_at = btrim(updated_at)
                         AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                         AND updated_at::timestamptz IS NOT NULL
                     ),
    CHECK (
        (state = 'active' AND remaining_milli > 0)
        OR (state IN ('consumed','reversed') AND remaining_milli = 0)
    )
);
CREATE INDEX IF NOT EXISTS idx_payment_credit_positions_user
    ON payment_credit_positions(user_id,state,created_at);

CREATE TABLE IF NOT EXISTS payment_credit_consumptions (
    id            TEXT PRIMARY KEY
                  CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    order_id      TEXT NOT NULL REFERENCES payment_credit_positions(order_id)
                  ON DELETE RESTRICT,
    usage_id      TEXT NOT NULL,
    amount_milli  BIGINT NOT NULL CHECK (amount_milli > 0),
    state         TEXT NOT NULL CHECK (state IN ('consumed','restored')),
    created_at    TEXT NOT NULL CHECK (
                      created_at = btrim(created_at)
                      AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                      AND created_at::timestamptz IS NOT NULL
                  ),
    updated_at    TEXT NOT NULL CHECK (
                      updated_at = btrim(updated_at)
                      AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                      AND updated_at::timestamptz IS NOT NULL
                  ),
    UNIQUE(order_id,usage_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_credit_consumptions_usage
    ON payment_credit_consumptions(usage_id,state);

CREATE TABLE IF NOT EXISTS payment_reconciliation_runs (
    id                    TEXT PRIMARY KEY
                          CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    provider              TEXT NOT NULL CHECK (provider = 'adapay'),
    provider_mode         TEXT NOT NULL CHECK (provider_mode IN ('mock','live')),
    bill_date             DATE NOT NULL,
    source_sha256         TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    row_count             INTEGER NOT NULL CHECK (row_count BETWEEN 0 AND 10000),
    payment_total_fen     BIGINT NOT NULL CHECK (payment_total_fen >= 0),
    refund_total_fen      BIGINT NOT NULL CHECK (refund_total_fen >= 0),
    discrepancy_count     INTEGER NOT NULL CHECK (discrepancy_count >= 0),
    status                TEXT NOT NULL
                          CHECK (status IN ('matched','discrepancies','needs_manual')),
    created_at            TEXT NOT NULL CHECK (
                              created_at = btrim(created_at)
                              AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                              AND created_at::timestamptz IS NOT NULL
                          ),
    completed_at          TEXT NOT NULL CHECK (
                              completed_at = btrim(completed_at)
                              AND completed_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                              AND completed_at::timestamptz IS NOT NULL
                          ),
    UNIQUE(provider,provider_mode,bill_date,source_sha256),
    CHECK (created_at::timestamptz <= completed_at::timestamptz)
);
CREATE INDEX IF NOT EXISTS idx_payment_reconciliation_date
    ON payment_reconciliation_runs(provider_mode,bill_date);

CREATE TABLE IF NOT EXISTS payment_reconciliation_items (
    id                TEXT PRIMARY KEY
                      CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    run_id            TEXT NOT NULL REFERENCES payment_reconciliation_runs(id)
                      ON DELETE RESTRICT,
    entry_kind        TEXT NOT NULL CHECK (entry_kind IN ('payment','refund')),
    reference_hash    TEXT NOT NULL CHECK (reference_hash ~ '^[0-9a-f]{64}$'),
    issue_code        TEXT NOT NULL CHECK (
                          issue_code IN (
                              'missing_local','missing_provider',
                              'amount_mismatch','status_mismatch'
                          )
                      ),
    local_fen         BIGINT,
    provider_fen      BIGINT,
    resolution_state TEXT NOT NULL
                      CHECK (resolution_state IN ('open','accepted','resolved')),
    created_at        TEXT NOT NULL CHECK (
                          created_at = btrim(created_at)
                          AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                          AND created_at::timestamptz IS NOT NULL
                      ),
    UNIQUE(run_id,entry_kind,reference_hash,issue_code)
);

CREATE TABLE IF NOT EXISTS payment_settlement_summaries (
    id               TEXT PRIMARY KEY
                     CHECK (id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    provider         TEXT NOT NULL CHECK (provider = 'adapay'),
    provider_mode    TEXT NOT NULL CHECK (provider_mode IN ('mock','live')),
    settlement_date  DATE NOT NULL,
    source_sha256    TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    gross_fen        BIGINT NOT NULL CHECK (gross_fen >= 0),
    refund_fen       BIGINT NOT NULL CHECK (refund_fen >= 0),
    fee_fen          BIGINT NOT NULL CHECK (fee_fen >= 0),
    net_fen          BIGINT NOT NULL CHECK (net_fen >= 0),
    status           TEXT NOT NULL CHECK (status IN ('verified','needs_manual')),
    created_at       TEXT NOT NULL CHECK (
                         created_at = btrim(created_at)
                         AND created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$'
                         AND created_at::timestamptz IS NOT NULL
                     ),
    UNIQUE(provider,provider_mode,settlement_date,source_sha256),
    CHECK (gross_fen-refund_fen-fee_fen = net_fen)
);

CREATE OR REPLACE FUNCTION noteai_payment_order_identity_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.subject_hash <> OLD.subject_hash
       OR NEW.product_kind <> OLD.product_kind
       OR NEW.product_id <> OLD.product_id
       OR NEW.catalog_version <> OLD.catalog_version
       OR NEW.amount_fen <> OLD.amount_fen
       OR NEW.currency <> OLD.currency
       OR NEW.provider <> OLD.provider
       OR NEW.provider_mode <> OLD.provider_mode
       OR NEW.merchant_order_no <> OLD.merchant_order_no
       OR NEW.app_id_hash <> OLD.app_id_hash
       OR NEW.idempotency_key_hash <> OLD.idempotency_key_hash
       OR NEW.request_hash <> OLD.request_hash
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'payment order identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.user_id IS DISTINCT FROM OLD.user_id
       AND (
            OLD.user_id IS NULL
            OR NEW.user_id IS NOT NULL
            OR NEW.provider_payment_id IS DISTINCT FROM OLD.provider_payment_id
            OR NEW.payment_status <> OLD.payment_status
            OR NEW.entitlement_status <> OLD.entitlement_status
            OR NEW.entitlement_ref IS DISTINCT FROM OLD.entitlement_ref
            OR NEW.refund_status <> OLD.refund_status
            OR NEW.refunded_fen <> OLD.refunded_fen
            OR NEW.refund_count <> OLD.refund_count
            OR NEW.updated_at <> OLD.updated_at
            OR NEW.succeeded_at IS DISTINCT FROM OLD.succeeded_at
            OR NEW.terminal_at IS DISTINCT FROM OLD.terminal_at
       ) THEN
        RAISE EXCEPTION 'payment order user join is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (OLD.payment_status = 'created'
            AND NEW.payment_status NOT IN (
                'created','pending','succeeded','failed','closed','needs_manual'
            ))
       OR (OLD.payment_status = 'pending'
            AND NEW.payment_status NOT IN (
                'pending','succeeded','failed','closed','needs_manual'
            ))
       OR (OLD.payment_status = 'succeeded'
            AND NEW.payment_status <> 'succeeded')
       OR (OLD.payment_status IN ('failed','closed')
            AND NEW.payment_status NOT IN (OLD.payment_status,'needs_manual'))
       OR (OLD.payment_status = 'needs_manual'
            AND NEW.payment_status <> 'needs_manual')
       OR (OLD.entitlement_status = 'pending'
            AND NEW.entitlement_status NOT IN (
                'pending','applied','needs_manual'
            ))
       OR (OLD.entitlement_status = 'applied'
            AND NEW.entitlement_status NOT IN (
                'applied','reversed','needs_manual'
            ))
       OR (OLD.entitlement_status = 'reversed'
            AND NEW.entitlement_status <> 'reversed')
       OR (OLD.refund_status = 'none'
            AND NEW.refund_status NOT IN ('none','pending','needs_manual'))
       OR (OLD.refund_status = 'pending'
            AND NEW.refund_status NOT IN (
                'pending','refunded','needs_manual'
            ))
       OR (OLD.refund_status = 'refunded'
            AND NEW.refund_status <> 'refunded')
       OR (OLD.refund_status = 'needs_manual'
            AND NEW.refund_status <> 'needs_manual')
       OR NEW.refunded_fen < OLD.refunded_fen
       OR NEW.refund_count < OLD.refund_count
       OR (
            OLD.provider_payment_id IS NOT NULL
            AND NEW.provider_payment_id IS DISTINCT FROM OLD.provider_payment_id
       ) THEN
        RAISE EXCEPTION 'invalid payment order transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_order_identity_v1 ON payment_orders;
CREATE TRIGGER noteai_payment_order_identity_v1
BEFORE UPDATE ON payment_orders
FOR EACH ROW EXECUTE FUNCTION noteai_payment_order_identity_guard_v1();

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
       ) THEN
        RAISE EXCEPTION 'invalid payment refund transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_refund_identity_v1 ON payment_refunds;
CREATE TRIGGER noteai_payment_refund_identity_v1
BEFORE UPDATE ON payment_refunds
FOR EACH ROW EXECUTE FUNCTION noteai_payment_refund_identity_guard_v1();

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
            )) THEN
        RAISE EXCEPTION 'invalid payment event transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_event_identity_v1 ON payment_events;
CREATE TRIGGER noteai_payment_event_identity_v1
BEFORE UPDATE ON payment_events
FOR EACH ROW EXECUTE FUNCTION noteai_payment_event_identity_guard_v1();

CREATE OR REPLACE FUNCTION noteai_payment_credit_position_identity_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.order_id <> OLD.order_id
       OR NEW.subject_hash <> OLD.subject_hash
       OR NEW.granted_milli <> OLD.granted_milli
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'payment credit position identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_credit_position_identity_v1
    ON payment_credit_positions;
CREATE TRIGGER noteai_payment_credit_position_identity_v1
BEFORE UPDATE ON payment_credit_positions
FOR EACH ROW
EXECUTE FUNCTION noteai_payment_credit_position_identity_guard_v1();

CREATE OR REPLACE FUNCTION noteai_payment_credit_position_user_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF (OLD.user_id IS NULL AND NEW.user_id IS NOT NULL)
       OR (
            OLD.user_id IS NOT NULL
            AND NEW.user_id IS NOT NULL
            AND NEW.user_id IS DISTINCT FROM OLD.user_id
       ) THEN
        RAISE EXCEPTION 'payment credit position user is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_credit_position_user_v1
    ON payment_credit_positions;
CREATE TRIGGER noteai_payment_credit_position_user_v1
BEFORE UPDATE OF user_id ON payment_credit_positions
FOR EACH ROW
EXECUTE FUNCTION noteai_payment_credit_position_user_guard_v1();

CREATE OR REPLACE FUNCTION noteai_payment_credit_consumption_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.order_id <> OLD.order_id
       OR NEW.usage_id <> OLD.usage_id
       OR NEW.amount_milli <> OLD.amount_milli
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'payment credit consumption identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF (OLD.state = 'consumed'
            AND NEW.state NOT IN ('consumed','restored'))
       OR (OLD.state = 'restored' AND NEW.state <> 'restored') THEN
        RAISE EXCEPTION 'invalid payment credit consumption transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS noteai_payment_credit_consumption_v1
    ON payment_credit_consumptions;
CREATE TRIGGER noteai_payment_credit_consumption_v1
BEFORE UPDATE ON payment_credit_consumptions
FOR EACH ROW
EXECUTE FUNCTION noteai_payment_credit_consumption_guard_v1();

CREATE OR REPLACE FUNCTION noteai_payment_refund_insert_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT EXISTS (
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
DROP TRIGGER IF EXISTS noteai_payment_refund_insert_v1 ON payment_refunds;
CREATE TRIGGER noteai_payment_refund_insert_v1
BEFORE INSERT ON payment_refunds
FOR EACH ROW EXECUTE FUNCTION noteai_payment_refund_insert_guard_v1();

CREATE OR REPLACE FUNCTION noteai_payment_append_only_guard_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    RAISE EXCEPTION 'payment ledger is append only'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS noteai_payment_cash_no_update_v1
    ON payment_cash_ledger;
CREATE TRIGGER noteai_payment_cash_no_update_v1
BEFORE UPDATE OR DELETE ON payment_cash_ledger
FOR EACH ROW EXECUTE FUNCTION noteai_payment_append_only_guard_v1();

DROP TRIGGER IF EXISTS noteai_payment_entitlement_no_update_v1
    ON payment_entitlement_ledger;
CREATE TRIGGER noteai_payment_entitlement_no_update_v1
BEFORE UPDATE OR DELETE ON payment_entitlement_ledger
FOR EACH ROW EXECUTE FUNCTION noteai_payment_append_only_guard_v1();

DROP TRIGGER IF EXISTS noteai_payment_settlement_no_update_v1
    ON payment_settlement_summaries;
CREATE TRIGGER noteai_payment_settlement_no_update_v1
BEFORE UPDATE OR DELETE ON payment_settlement_summaries
FOR EACH ROW EXECUTE FUNCTION noteai_payment_append_only_guard_v1();

DROP TRIGGER IF EXISTS noteai_payment_reconciliation_run_no_update_v1
    ON payment_reconciliation_runs;
CREATE TRIGGER noteai_payment_reconciliation_run_no_update_v1
BEFORE UPDATE OR DELETE ON payment_reconciliation_runs
FOR EACH ROW EXECUTE FUNCTION noteai_payment_append_only_guard_v1();

DROP TRIGGER IF EXISTS noteai_payment_reconciliation_item_no_update_v1
    ON payment_reconciliation_items;
CREATE TRIGGER noteai_payment_reconciliation_item_no_update_v1
BEFORE UPDATE OR DELETE ON payment_reconciliation_items
FOR EACH ROW EXECUTE FUNCTION noteai_payment_append_only_guard_v1();

ALTER TABLE payment_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_refunds ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_cash_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_entitlement_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_credit_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_credit_consumptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reconciliation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reconciliation_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_settlement_summaries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS noteai_payment_orders_read_v1 ON payment_orders;
CREATE POLICY noteai_payment_orders_read_v1 ON payment_orders
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_app','noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_orders_insert_v1 ON payment_orders;
CREATE POLICY noteai_payment_orders_insert_v1 ON payment_orders
FOR INSERT TO PUBLIC
WITH CHECK (
    current_user = 'noteai_app'
    AND user_id IS NOT NULL
    AND provider_payment_id IS NULL
    AND payment_status = 'created'
    AND entitlement_status = 'pending'
    AND entitlement_ref IS NULL
    AND refund_status = 'none'
    AND refunded_fen = 0
    AND refund_count = 0
    AND succeeded_at IS NULL
    AND terminal_at IS NULL
);
DROP POLICY IF EXISTS noteai_payment_orders_update_v1 ON payment_orders;
CREATE POLICY noteai_payment_orders_update_v1 ON payment_orders
FOR UPDATE TO PUBLIC
USING (current_user IN ('noteai_app','noteai_payment'))
WITH CHECK (
    current_user = 'noteai_payment'
    OR (
        current_user = 'noteai_app'
        AND (
            user_id IS NULL
            OR (
                payment_status IN (
                    'created','pending','closed','needs_manual'
                )
                AND entitlement_status = 'pending'
                AND refund_status = 'none'
                AND refunded_fen = 0
                AND refund_count = 0
            )
        )
    )
);

DROP POLICY IF EXISTS noteai_payment_refunds_read_v1 ON payment_refunds;
CREATE POLICY noteai_payment_refunds_read_v1 ON payment_refunds
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_refunds_write_v1 ON payment_refunds;
CREATE POLICY noteai_payment_refunds_write_v1 ON payment_refunds
FOR ALL TO PUBLIC
USING (current_user = 'noteai_payment')
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_events_read_v1 ON payment_events;
CREATE POLICY noteai_payment_events_read_v1 ON payment_events
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_events_write_v1 ON payment_events;
CREATE POLICY noteai_payment_events_write_v1 ON payment_events
FOR ALL TO PUBLIC
USING (current_user = 'noteai_payment')
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_cash_read_v1 ON payment_cash_ledger;
CREATE POLICY noteai_payment_cash_read_v1 ON payment_cash_ledger
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_cash_insert_v1 ON payment_cash_ledger;
CREATE POLICY noteai_payment_cash_insert_v1 ON payment_cash_ledger
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_entitlement_read_v1
    ON payment_entitlement_ledger;
CREATE POLICY noteai_payment_entitlement_read_v1
    ON payment_entitlement_ledger
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_entitlement_insert_v1
    ON payment_entitlement_ledger;
CREATE POLICY noteai_payment_entitlement_insert_v1
    ON payment_entitlement_ledger
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_positions_read_v1
    ON payment_credit_positions;
CREATE POLICY noteai_payment_positions_read_v1
    ON payment_credit_positions
FOR SELECT TO PUBLIC
USING (
    current_user IN (
        'noteai_app','noteai_payment','noteai_admin','noteai_ai_worker'
    )
);
DROP POLICY IF EXISTS noteai_payment_positions_insert_v1
    ON payment_credit_positions;
CREATE POLICY noteai_payment_positions_insert_v1
    ON payment_credit_positions
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');
DROP POLICY IF EXISTS noteai_payment_positions_update_v1
    ON payment_credit_positions;
CREATE POLICY noteai_payment_positions_update_v1
    ON payment_credit_positions
FOR UPDATE TO PUBLIC
USING (
    current_user IN ('noteai_app','noteai_payment','noteai_ai_worker')
)
WITH CHECK (
    current_user IN ('noteai_app','noteai_payment','noteai_ai_worker')
);

DROP POLICY IF EXISTS noteai_payment_consumptions_read_v1
    ON payment_credit_consumptions;
CREATE POLICY noteai_payment_consumptions_read_v1
    ON payment_credit_consumptions
FOR SELECT TO PUBLIC
USING (
    current_user IN (
        'noteai_app','noteai_payment','noteai_admin','noteai_ai_worker'
    )
);
DROP POLICY IF EXISTS noteai_payment_consumptions_insert_v1
    ON payment_credit_consumptions;
CREATE POLICY noteai_payment_consumptions_insert_v1
    ON payment_credit_consumptions
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_app');
DROP POLICY IF EXISTS noteai_payment_consumptions_update_v1
    ON payment_credit_consumptions;
CREATE POLICY noteai_payment_consumptions_update_v1
    ON payment_credit_consumptions
FOR UPDATE TO PUBLIC
USING (current_user IN ('noteai_app','noteai_ai_worker'))
WITH CHECK (current_user IN ('noteai_app','noteai_ai_worker'));

DROP POLICY IF EXISTS noteai_payment_reconciliation_runs_read_v1
    ON payment_reconciliation_runs;
CREATE POLICY noteai_payment_reconciliation_runs_read_v1
    ON payment_reconciliation_runs
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_reconciliation_runs_insert_v1
    ON payment_reconciliation_runs;
CREATE POLICY noteai_payment_reconciliation_runs_insert_v1
    ON payment_reconciliation_runs
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_reconciliation_items_read_v1
    ON payment_reconciliation_items;
CREATE POLICY noteai_payment_reconciliation_items_read_v1
    ON payment_reconciliation_items
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_reconciliation_items_insert_v1
    ON payment_reconciliation_items;
CREATE POLICY noteai_payment_reconciliation_items_insert_v1
    ON payment_reconciliation_items
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');

DROP POLICY IF EXISTS noteai_payment_settlements_read_v1
    ON payment_settlement_summaries;
CREATE POLICY noteai_payment_settlements_read_v1
    ON payment_settlement_summaries
FOR SELECT TO PUBLIC
USING (current_user IN ('noteai_payment','noteai_admin'));
DROP POLICY IF EXISTS noteai_payment_settlements_insert_v1
    ON payment_settlement_summaries;
CREATE POLICY noteai_payment_settlements_insert_v1
    ON payment_settlement_summaries
FOR INSERT TO PUBLIC
WITH CHECK (current_user = 'noteai_payment');
