-- Credential-free first-launch production runtime-role ACL.
--
-- The migration owner executes this file in the same transaction as
-- migrations 0009-0016. New roles are created NOLOGIN and remain inert until
-- the separate managed-secret task enables LOGIN with generated credentials.
-- Existing noteai_app/noteai_xhs credentials and role attributes are never
-- changed here.

DO $contract$
DECLARE
    role_name TEXT;
    role_row RECORD;
BEGIN
    IF session_user = 'noteai_xhs'
       OR current_user = 'noteai_xhs'
       OR session_user <> current_user
       OR current_user <> current_role THEN
        RAISE EXCEPTION 'runtime role cannot execute migrations';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'noteai_app')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'noteai_xhs') THEN
        RAISE EXCEPTION 'required historical runtime roles are absent';
    END IF;

    FOREACH role_name IN ARRAY ARRAY[
        'noteai_admin_runtime',
        'noteai_ai_dispatcher',
        'noteai_ai_worker',
        'noteai_payment',
        'noteai_xhs_tracking',
        'noteai_xhs_trends'
    ]
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        END IF;
    END LOOP;

    FOREACH role_name IN ARRAY ARRAY[
        'noteai_app',
        'noteai_admin_runtime',
        'noteai_ai_dispatcher',
        'noteai_ai_worker',
        'noteai_payment',
        'noteai_xhs',
        'noteai_xhs_tracking',
        'noteai_xhs_trends'
    ]
    LOOP
        SELECT * INTO role_row FROM pg_roles WHERE rolname = role_name;
        IF role_row.rolsuper
           OR (role_row.rolinherit AND role_name <> 'noteai_app')
           OR (NOT role_row.rolinherit AND role_name = 'noteai_app')
           OR role_row.rolcreaterole
           OR role_row.rolcreatedb
           OR role_row.rolreplication
           OR role_row.rolbypassrls THEN
            RAISE EXCEPTION 'runtime role attributes violate contract';
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_class object
            WHERE object.relowner = role_row.oid
        ) OR EXISTS (
            SELECT 1 FROM pg_namespace object
            WHERE object.nspowner = role_row.oid
        ) OR EXISTS (
            SELECT 1 FROM pg_proc object
            WHERE object.proowner = role_row.oid
        ) THEN
            RAISE EXCEPTION 'runtime role ownership violates contract';
        END IF;
    END LOOP;

    IF (
        SELECT COUNT(*)
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid = membership.roleid
        JOIN pg_roles member ON member.oid = membership.member
        WHERE granted.rolname = ANY(ARRAY[
            'noteai_app',
            'noteai_admin_runtime',
            'noteai_ai_dispatcher',
            'noteai_ai_worker',
            'noteai_payment',
            'noteai_xhs',
            'noteai_xhs_tracking',
            'noteai_xhs_trends'
        ])
        OR member.rolname = ANY(ARRAY[
            'noteai_app',
            'noteai_admin_runtime',
            'noteai_ai_dispatcher',
            'noteai_ai_worker',
            'noteai_payment',
            'noteai_xhs',
            'noteai_xhs_tracking',
            'noteai_xhs_trends'
        ])
    ) <> 1 OR NOT EXISTS (
        SELECT 1
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid = membership.roleid
        JOIN pg_roles member ON member.oid = membership.member
        WHERE granted.rolname = 'noteai_xhs'
          AND member.rolname = 'noteai_admin'
          AND membership.admin_option
          AND (
              to_jsonb(membership)->>'inherit_option'
          )::boolean IS TRUE
          AND (
              to_jsonb(membership)->>'set_option'
          )::boolean IS FALSE
    ) THEN
        RAISE EXCEPTION 'accepted runtime role membership changed';
    END IF;
END
$contract$;

DO $database_acl$
DECLARE
    role_name TEXT;
BEGIN
    EXECUTE format(
        'REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC',
        current_database()
    );
    FOREACH role_name IN ARRAY ARRAY[
        'noteai_app',
        'noteai_admin_runtime',
        'noteai_ai_dispatcher',
        'noteai_ai_worker',
        'noteai_payment',
        'noteai_xhs',
        'noteai_xhs_tracking',
        'noteai_xhs_trends'
    ]
    LOOP
        EXECUTE format(
            'REVOKE CREATE, TEMPORARY ON DATABASE %I FROM %I',
            current_database(),
            role_name
        );
        EXECUTE format(
            'GRANT CONNECT ON DATABASE %I TO %I',
            current_database(),
            role_name
        );
        EXECUTE format(
            'REVOKE CREATE ON SCHEMA public FROM %I',
            role_name
        );
        EXECUTE format(
            'GRANT USAGE ON SCHEMA public TO %I',
            role_name
        );
    END LOOP;
END
$database_acl$;

DO $clear_new_roles$
DECLARE
    role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'noteai_admin_runtime',
        'noteai_ai_dispatcher',
        'noteai_ai_worker',
        'noteai_payment',
        'noteai_xhs_tracking',
        'noteai_xhs_trends'
    ]
    LOOP
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I',
            role_name
        );
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I',
            role_name
        );
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM %I',
            role_name
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            'REVOKE ALL PRIVILEGES ON TABLES FROM %I',
            role_name
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            'REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
            role_name
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            'REVOKE ALL PRIVILEGES ON FUNCTIONS FROM %I',
            role_name
        );
    END LOOP;
END
$clear_new_roles$;

-- Migration 0009: existing API role additions and contractions.
REVOKE ALL PRIVILEGES ON
    auth_login_limits,
    auth_verification_challenges,
    content_retention,
    account_deletion_requests,
    user_contract_acceptances
FROM noteai_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON auth_login_limits TO noteai_app;
GRANT SELECT, INSERT, UPDATE
    ON auth_verification_challenges TO noteai_app;
GRANT SELECT, INSERT ON content_retention TO noteai_app;
GRANT UPDATE(
    active_until,
    recovery_until,
    deleted_at,
    purge_after,
    purged_at,
    updated_at
) ON content_retention TO noteai_app;
GRANT SELECT, INSERT, UPDATE
    ON account_deletion_requests TO noteai_app;
GRANT SELECT, INSERT
    ON user_contract_acceptances TO noteai_app;

REVOKE UPDATE ON notes FROM noteai_app;
GRANT UPDATE(parent_id) ON notes TO noteai_app;
REVOKE UPDATE ON saved_diagnoses FROM noteai_app;
GRANT DELETE ON ai_operation_admissions TO noteai_app;
GRANT DELETE ON chat_sessions TO noteai_app;
GRANT UPDATE(user_id) ON credit_transactions TO noteai_app;
GRANT DELETE ON user_learn TO noteai_app;
GRANT DELETE ON users TO noteai_app;

-- Migration 0010: dedicated Tracking role.
GRANT SELECT ON tracked_notes TO noteai_xhs_tracking;
GRANT UPDATE(
    claim_token,
    claim_expires_at,
    active_attempt_id,
    note_title,
    likes_24h,
    saves_24h,
    comments_24h,
    check_24h_at,
    likes_7d,
    saves_7d,
    comments_7d,
    check_7d_at,
    views_est,
    next_check_at,
    last_checked_at,
    attempt_count,
    actual_ces,
    confidence,
    confidence_label,
    evidence_source,
    training_eligible,
    status,
    last_error_code,
    last_error,
    completed_at,
    insights_json
) ON tracked_notes TO noteai_xhs_tracking;
GRANT SELECT, INSERT
    ON tracking_provider_attempts TO noteai_xhs_tracking;
GRANT UPDATE(status, completed_at, error_code)
    ON tracking_provider_attempts TO noteai_xhs_tracking;
GRANT INSERT ON
    growth_records,
    user_memories,
    crawler_events
TO noteai_xhs_tracking;
GRANT SELECT ON system_settings TO noteai_xhs_tracking;
GRANT USAGE ON SEQUENCE crawler_events_id_seq TO noteai_xhs_tracking;

-- Migration 0011: dedicated Trends role and the API freshness projection.
GRANT SELECT, INSERT ON hot_keywords TO noteai_xhs_trends;
GRANT UPDATE(
    search_vol,
    trend_dir,
    source,
    sample_count,
    quality_score,
    evidence_level,
    quality_reason,
    captured_at
) ON hot_keywords TO noteai_xhs_trends;
GRANT SELECT, INSERT ON keyword_snapshots TO noteai_xhs_trends;
GRANT SELECT, INSERT ON xhs_crawler_health TO noteai_xhs_trends;
GRANT SELECT, INSERT ON xhs_freshness_ledger TO noteai_xhs_trends;
GRANT UPDATE(
    source,
    evidence_count,
    status,
    acquired_at,
    fresh_until,
    last_run_id,
    details_json
) ON xhs_freshness_ledger TO noteai_xhs_trends;
GRANT SELECT, INSERT ON xhs_trends_runs TO noteai_xhs_trends;
GRANT UPDATE(
    status,
    completed_at,
    provider_attempt_count,
    last_error_code,
    snapshot_sha256,
    snapshot_size
) ON xhs_trends_runs TO noteai_xhs_trends;
GRANT SELECT, INSERT
    ON xhs_trends_provider_attempts TO noteai_xhs_trends;
GRANT UPDATE(status, completed_at, error_code)
    ON xhs_trends_provider_attempts TO noteai_xhs_trends;
GRANT SELECT ON xhs_trends_service_state TO noteai_xhs_trends;
GRANT UPDATE(
    active_run_id,
    status,
    lease_token_hash,
    lease_fence,
    lease_expires_at,
    session_blocked,
    session_block_reason,
    session_blocked_at,
    updated_at
) ON xhs_trends_service_state TO noteai_xhs_trends;
GRANT SELECT, INSERT
    ON xhs_trends_snapshot_evidence TO noteai_xhs_trends;
GRANT USAGE ON SEQUENCE
    hot_keywords_id_seq,
    keyword_snapshots_id_seq
TO noteai_xhs_trends;
GRANT SELECT(id, status, completed_at)
    ON xhs_trends_runs TO noteai_app;

-- Migration 0012: API, dispatcher and Worker durable-AI surfaces.
GRANT SELECT, INSERT ON ai_payload_refs TO noteai_app;
GRANT UPDATE(state, deleted_at) ON ai_payload_refs TO noteai_app;
GRANT INSERT ON ai_operation_outbox TO noteai_app;
GRANT SELECT(id, operation_id, state)
    ON ai_operation_outbox TO noteai_app;
GRANT UPDATE(state, updated_at)
    ON ai_operation_outbox TO noteai_app;
GRANT SELECT, INSERT ON ai_operation_settlements TO noteai_app;
GRANT UPDATE(
    billing_state,
    failure_code,
    updated_at,
    settled_at
) ON ai_operation_settlements TO noteai_app;

GRANT SELECT ON
    ai_operation_outbox,
    ai_dispatch_state
TO noteai_ai_dispatcher;
GRANT SELECT(id, priority)
    ON ai_operations TO noteai_ai_dispatcher;
GRANT UPDATE(
    state,
    available_at,
    attempt_count,
    lease_owner_hash,
    lease_fence,
    lease_expires_at,
    updated_at,
    delivered_at
) ON ai_operation_outbox TO noteai_ai_dispatcher;
GRANT UPDATE(priority_streak, updated_at)
    ON ai_dispatch_state TO noteai_ai_dispatcher;

GRANT SELECT, INSERT ON ai_payload_refs TO noteai_ai_worker;
GRANT UPDATE(state, deleted_at) ON ai_payload_refs TO noteai_ai_worker;
GRANT SELECT ON
    ai_operations,
    ai_operation_events,
    ai_provider_attempts,
    ai_operation_admissions,
    ai_operation_settlements,
    idempotency_requests
TO noteai_ai_worker;
GRANT INSERT ON
    ai_operation_events,
    ai_provider_attempts
TO noteai_ai_worker;
GRANT UPDATE(
    status,
    provider_phase,
    lease_owner_hash,
    lease_fence,
    lease_expires_at,
    heartbeat_at,
    claim_count,
    provider_attempt_count,
    event_sequence,
    result_hash,
    result_count,
    updated_at,
    started_at,
    terminal_at
) ON ai_operations TO noteai_ai_worker;
GRANT UPDATE(
    state,
    response_hash,
    output_count,
    updated_at,
    terminal_at
) ON ai_provider_attempts TO noteai_ai_worker;
GRANT UPDATE(
    status,
    refund_applied,
    failure_code,
    refunded_at,
    failed_at,
    complete_applied,
    completed_at,
    updated_at
) ON idempotency_requests TO noteai_ai_worker;
GRANT UPDATE(
    result_ref_id,
    billing_state,
    failure_code,
    updated_at,
    settled_at
) ON ai_operation_settlements TO noteai_ai_worker;
GRANT SELECT(id, deletion_requested_at) ON users TO noteai_ai_worker;
GRANT UPDATE(used_monthly_credits) ON subscriptions TO noteai_ai_worker;
GRANT SELECT(user_id, balance) ON credits TO noteai_ai_worker;
GRANT INSERT ON credits TO noteai_ai_worker;
GRANT UPDATE(balance, total_used, updated_at) ON credits TO noteai_ai_worker;
GRANT INSERT ON credit_transactions TO noteai_ai_worker;
GRANT UPDATE(source, credits_used) ON usage_records TO noteai_ai_worker;
GRANT INSERT ON model_usage_records TO noteai_ai_worker;

-- Migration 0013: private object metadata.
GRANT SELECT, INSERT ON private_media_refs TO noteai_app;
GRANT UPDATE(state, deleted_at) ON private_media_refs TO noteai_app;
GRANT SELECT, INSERT ON ai_operation_media_refs TO noteai_app;
GRANT SELECT(id, subject_hash) ON ai_operations TO noteai_app;
GRANT SELECT ON
    private_media_refs,
    ai_operation_media_refs
TO noteai_ai_worker;

-- Migration 0014: provider-isolated payment surfaces.
REVOKE ALL ON FUNCTION
    noteai_validate_operation_media_link_v1(),
    noteai_payment_order_identity_guard_v1(),
    noteai_payment_refund_identity_guard_v1(),
    noteai_payment_event_identity_guard_v1(),
    noteai_payment_credit_position_identity_guard_v1(),
    noteai_payment_credit_position_user_guard_v1(),
    noteai_payment_credit_consumption_guard_v1(),
    noteai_payment_refund_insert_guard_v1(),
    noteai_payment_append_only_guard_v1()
FROM PUBLIC;

GRANT SELECT, INSERT ON payment_orders TO noteai_app;
GRANT UPDATE(
    user_id,
    provider_payment_id,
    payment_status,
    updated_at,
    terminal_at
) ON payment_orders TO noteai_app;
GRANT SELECT ON
    payment_credit_positions,
    payment_credit_consumptions
TO noteai_app;
GRANT UPDATE(user_id, remaining_milli, state, updated_at)
    ON payment_credit_positions TO noteai_app;
GRANT INSERT ON payment_credit_consumptions TO noteai_app;
GRANT UPDATE(state, updated_at)
    ON payment_credit_consumptions TO noteai_app;

GRANT SELECT ON
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
TO noteai_payment;
GRANT UPDATE(
    provider_payment_id,
    payment_status,
    entitlement_status,
    entitlement_ref,
    refund_status,
    refunded_fen,
    refund_count,
    updated_at,
    succeeded_at,
    terminal_at
) ON payment_orders TO noteai_payment;
GRANT INSERT ON
    payment_refunds,
    payment_events,
    payment_cash_ledger,
    payment_entitlement_ledger,
    payment_credit_positions,
    payment_reconciliation_runs,
    payment_reconciliation_items,
    payment_settlement_summaries
TO noteai_payment;
GRANT UPDATE(provider_refund_id, status, updated_at, terminal_at)
    ON payment_refunds TO noteai_payment;
GRANT UPDATE(
    processing_state,
    reason_code,
    order_id,
    refund_id,
    processed_at
) ON payment_events TO noteai_payment;
GRANT UPDATE(user_id, remaining_milli, state, updated_at)
    ON payment_credit_positions TO noteai_payment;
GRANT SELECT(id, deletion_requested_at) ON users TO noteai_payment;
GRANT SELECT(id, user_id, tier, started_at, is_active), INSERT
    ON subscriptions TO noteai_payment;
GRANT UPDATE(is_active) ON subscriptions TO noteai_payment;
GRANT SELECT(user_id, balance, total_purchased), INSERT
    ON credits TO noteai_payment;
GRANT UPDATE(balance, total_purchased, updated_at)
    ON credits TO noteai_payment;
GRANT INSERT ON credit_transactions TO noteai_payment;
GRANT SELECT(user_id, recorded_at, credits_used, source)
    ON usage_records TO noteai_payment;

GRANT SELECT ON
    payment_credit_positions,
    payment_credit_consumptions
TO noteai_ai_worker;
GRANT UPDATE(remaining_milli, state, updated_at)
    ON payment_credit_positions TO noteai_ai_worker;
GRANT UPDATE(state, updated_at)
    ON payment_credit_consumptions TO noteai_ai_worker;

-- Migrations 0015-0016: dedicated Admin runtime role.
GRANT SELECT, INSERT, DELETE
    ON admin_sessions TO noteai_admin_runtime;
GRANT SELECT(
    id,
    username,
    email,
    phone,
    nickname,
    avatar_emoji,
    created_at,
    last_login
) ON users TO noteai_admin_runtime;
GRANT SELECT(id, user_id, score) ON notes TO noteai_admin_runtime;
GRANT SELECT(
    user_id,
    type,
    amount,
    balance_after,
    description,
    paid_rmb,
    package_id,
    recorded_at
) ON credit_transactions TO noteai_admin_runtime;
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
TO noteai_admin_runtime;
