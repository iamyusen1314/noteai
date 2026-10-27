-- Additive JSAPI identity; existing Native orders retain NULL and original hashes.
ALTER TABLE public.payment_orders ADD COLUMN wechat_jsapi_payer_hash TEXT
    CHECK(wechat_jsapi_payer_hash IS NULL OR
        (provider='wechatpay_direct' AND wechat_jsapi_payer_hash ~ '^[0-9a-f]{64}$'));
ALTER TABLE public.payment_orders ADD COLUMN wechat_jsapi_last_query_at BIGINT
    CHECK(wechat_jsapi_last_query_at IS NULL OR
        (wechat_jsapi_payer_hash IS NOT NULL
         AND wechat_jsapi_last_query_at BETWEEN 946684800 AND 4102444800));
CREATE FUNCTION public.noteai_payment_jsapi_identity_guard_v1() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.wechat_jsapi_payer_hash IS DISTINCT FROM OLD.wechat_jsapi_payer_hash THEN
        RAISE EXCEPTION 'payment payer identity is immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.wechat_jsapi_last_query_at IS DISTINCT FROM OLD.wechat_jsapi_last_query_at
       AND (NEW.wechat_jsapi_last_query_at IS NULL
            OR (OLD.wechat_jsapi_last_query_at IS NOT NULL
                AND NEW.wechat_jsapi_last_query_at<=OLD.wechat_jsapi_last_query_at)) THEN
        RAISE EXCEPTION 'payment query clock must advance' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER noteai_payment_jsapi_identity_v1 BEFORE UPDATE ON public.payment_orders
FOR EACH ROW EXECUTE FUNCTION public.noteai_payment_jsapi_identity_guard_v1();

-- No OpenID, OAuth token, AppSecret or NoteAI bearer is stored in plaintext.
CREATE TABLE public.payment_wechat_oauth_states (
    state_hash TEXT PRIMARY KEY CHECK(state_hash ~ '^[0-9a-f]{64}$'),
    user_id TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL CHECK(session_hash ~ '^[0-9a-f]{64}$'),
    app_id TEXT NOT NULL CHECK(app_id ~ '^wx[0-9a-f]{16}$'),
    product_kind TEXT NOT NULL CHECK(product_kind IN ('subscription','credit_package')),
    product_id TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL CHECK(idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK(status IN ('pending','exchanging','ready','failed','unknown')),
    openid_ciphertext TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL CHECK(expires_at>created_at),
    updated_at TEXT NOT NULL,
    CHECK((status='ready')=(openid_ciphertext IS NOT NULL))
);
CREATE INDEX idx_payment_wechat_oauth_user_created ON public.payment_wechat_oauth_states(user_id,created_at);
CREATE INDEX idx_payment_wechat_oauth_user_expiry ON public.payment_wechat_oauth_states(user_id,expires_at);
CREATE FUNCTION public.noteai_payment_wechat_oauth_guard_v1() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
    IF ROW(NEW.state_hash,NEW.user_id,NEW.session_hash,NEW.app_id,NEW.product_kind,
           NEW.product_id,NEW.idempotency_key_hash,NEW.created_at,NEW.expires_at)
       IS DISTINCT FROM
       ROW(OLD.state_hash,OLD.user_id,OLD.session_hash,OLD.app_id,OLD.product_kind,
           OLD.product_id,OLD.idempotency_key_hash,OLD.created_at,OLD.expires_at)
       OR NOT ((OLD.status='pending' AND NEW.status='exchanging')
           OR (OLD.status='exchanging' AND NEW.status IN ('ready','failed','unknown'))) THEN
        RAISE EXCEPTION 'invalid WeChat authorization transition' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER noteai_payment_wechat_oauth_identity_v1 BEFORE UPDATE ON public.payment_wechat_oauth_states
FOR EACH ROW EXECUTE FUNCTION public.noteai_payment_wechat_oauth_guard_v1();
ALTER TABLE public.payment_wechat_oauth_states ENABLE ROW LEVEL SECURITY;
CREATE POLICY noteai_payment_wechat_oauth_read_v1 ON public.payment_wechat_oauth_states
FOR SELECT TO PUBLIC USING(current_user='noteai_app'
    AND user_id=current_setting('noteai.jsapi_user_id',true));
CREATE POLICY noteai_payment_wechat_oauth_insert_v1 ON public.payment_wechat_oauth_states
FOR INSERT TO PUBLIC WITH CHECK(current_user='noteai_app'
    AND user_id=current_setting('noteai.jsapi_user_id',true)
    AND status='pending' AND openid_ciphertext IS NULL);
CREATE POLICY noteai_payment_wechat_oauth_update_v1 ON public.payment_wechat_oauth_states
FOR UPDATE TO PUBLIC USING(current_user='noteai_app'
    AND user_id=current_setting('noteai.jsapi_user_id',true))
WITH CHECK(current_user='noteai_app' AND user_id=current_setting('noteai.jsapi_user_id',true));
CREATE POLICY noteai_payment_wechat_oauth_delete_v1 ON public.payment_wechat_oauth_states
FOR DELETE TO PUBLIC USING(current_user='noteai_app'
    AND user_id=current_setting('noteai.jsapi_user_id',true)
    AND expires_at::timestamptz<=CURRENT_TIMESTAMP);

-- Defeat inherited/default ACLs before granting the one API role its narrow DML.
DO $$ DECLARE entry RECORD;
BEGIN
    FOR entry IN SELECT a.grantee FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
      WHERE n.nspname='public' AND c.relname='payment_wechat_oauth_states' AND a.grantee<>c.relowner
    LOOP
      EXECUTE format('REVOKE ALL ON public.payment_wechat_oauth_states FROM %s',
          CASE WHEN entry.grantee=0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(entry.grantee)) END);
    END LOOP;
END $$;
GRANT SELECT,INSERT,DELETE ON public.payment_wechat_oauth_states TO noteai_app;
GRANT UPDATE(status,openid_ciphertext,updated_at) ON public.payment_wechat_oauth_states TO noteai_app;
GRANT UPDATE(wechat_jsapi_last_query_at) ON public.payment_orders TO noteai_app;
REVOKE ALL ON FUNCTION public.noteai_payment_jsapi_identity_guard_v1(),
    public.noteai_payment_wechat_oauth_guard_v1() FROM PUBLIC;
