BEGIN;

DO $contract$
DECLARE
    role_row RECORD;
BEGIN
    SELECT * INTO role_row FROM pg_roles WHERE rolname = 'noteai_admin';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'noteai_admin role must be created by the credential workflow';
    END IF;
    IF role_row.rolsuper
       OR role_row.rolinherit
       OR role_row.rolcreaterole
       OR role_row.rolcreatedb
       OR NOT role_row.rolcanlogin
       OR role_row.rolreplication
       OR role_row.rolbypassrls THEN
        RAISE EXCEPTION 'noteai_admin role attributes violate runtime contract';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles member_role ON member_role.oid = m.member
        WHERE member_role.rolname = 'noteai_admin'
    ) THEN
        RAISE EXCEPTION 'noteai_admin must not inherit or SET ROLE to another role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_roles owner_role ON owner_role.oid = c.relowner
        WHERE owner_role.rolname = 'noteai_admin'
    ) OR EXISTS (
        SELECT 1 FROM pg_namespace n
        JOIN pg_roles owner_role ON owner_role.oid = n.nspowner
        WHERE owner_role.rolname = 'noteai_admin'
    ) OR EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_roles owner_role ON owner_role.oid = p.proowner
        WHERE owner_role.rolname = 'noteai_admin'
    ) THEN
        RAISE EXCEPTION 'noteai_admin must not own database objects';
    END IF;
END
$contract$;

DO $database_acl$
BEGIN
    EXECUTE format(
        'REVOKE ALL PRIVILEGES ON DATABASE %I FROM noteai_admin',
        current_database()
    );
    EXECUTE format(
        'REVOKE TEMP ON DATABASE %I FROM PUBLIC',
        current_database()
    );
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO noteai_admin',
        current_database()
    );
END
$database_acl$;

REVOKE ALL PRIVILEGES ON SCHEMA public FROM noteai_admin;
GRANT USAGE ON SCHEMA public TO noteai_admin;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM noteai_admin;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM noteai_admin;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM noteai_admin;

GRANT SELECT, INSERT, DELETE ON admin_sessions TO noteai_admin;

GRANT SELECT (
    id, username, email, phone, nickname, avatar_emoji, created_at, last_login
) ON users TO noteai_admin;
GRANT SELECT (id, user_id, score) ON notes TO noteai_admin;
GRANT SELECT (
    user_id, type, amount, balance_after, description, paid_rmb, package_id,
    recorded_at
) ON credit_transactions TO noteai_admin;

GRANT SELECT ON
    subscriptions,
    credits,
    usage_records,
    model_usage_records,
    managed_prompts,
    prompt_history,
    system_settings,
    tracked_notes,
    ai_operations,
    ai_operation_settlements,
    ai_operation_outbox,
    xhs_freshness_ledger,
    xhs_crawler_health,
    xhs_trends_runs,
    payment_orders,
    payment_refunds,
    payment_events,
    payment_cash_ledger,
    payment_entitlement_ledger,
    payment_credit_positions,
    payment_credit_consumptions,
    payment_reconciliation_runs,
    payment_reconciliation_items,
    payment_settlement_summaries
TO noteai_admin;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM noteai_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM noteai_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM noteai_admin;

COMMIT;
