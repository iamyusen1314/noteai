-- Owner's explicit September 7 test-account supplement; no migration.
-- Bind @@USER_ID@@ ONLY to the UUID returned by normal registration.
-- Gift semantics mirror billing.grant_credits with the existing user fence.
-- UNKNOWN means read back this exact ledger ID; never dispatch again.
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SET LOCAL search_path=pg_catalog,public;
SET LOCAL ROLE noteai_admin;
DO $owner_gift$
DECLARE
  target_user text := '@@USER_ID@@';
  matched_user text;
  resulting_balance numeric;
  written_rows integer;
  at_utc text := to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00';
BEGIN
  PERFORM target_user::uuid;
  IF current_database() <> 'noteai' OR current_user <> 'noteai_admin' THEN
    RAISE EXCEPTION 'owner_target_database_mismatch';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('noteai:user-write:' || target_user));
  SELECT id INTO matched_user FROM public.users
    WHERE id=target_user AND deletion_requested_at IS NULL
      AND encode(sha256(convert_to(username,'UTF8')),'hex')='56e5c09dfca80f6c2f70b328fc42af3c125bdd97c8beb47b93747f2e16cf7387'
      AND phone IS NULL AND phone_verified_at IS NULL
    FOR UPDATE;
  IF matched_user IS NULL THEN RAISE EXCEPTION 'exact_active_owner_account_required'; END IF;
  IF EXISTS (SELECT 1 FROM public.credit_transactions
      WHERE id='4437ee15-a944-507c-8e22-89c79c6ad6d3'
         OR description='owner-test-gift-20260907-900') THEN
    IF (SELECT count(*) FROM public.credit_transactions
        WHERE id='4437ee15-a944-507c-8e22-89c79c6ad6d3' AND user_id=target_user
          AND type='gift' AND amount=900 AND balance_after=900 AND paid_rmb=0
          AND package_id='' AND payment_ref='' AND description='owner-test-gift-20260907-900')=1
       AND (SELECT count(*) FROM public.credit_transactions WHERE user_id=target_user)=1
       AND EXISTS (SELECT 1 FROM public.credits WHERE user_id=target_user
          AND balance=900 AND total_purchased=0 AND total_used=0) THEN
      RAISE NOTICE 'exact_gift_already_present_no_write';
      RETURN;
    END IF;
    RAISE EXCEPTION 'gift_identity_or_balance_conflict';
  END IF;
  IF EXISTS (SELECT 1 FROM public.credits WHERE user_id=target_user
      AND (balance<>0 OR total_purchased<>0 OR total_used<>0))
     OR EXISTS (SELECT 1 FROM public.credit_transactions WHERE user_id=target_user) THEN
    RAISE EXCEPTION 'new_owner_credit_state_required';
  END IF;
  INSERT INTO public.credits(user_id,balance,total_purchased,total_used,updated_at)
    VALUES(target_user,0,0,0,at_utc) ON CONFLICT(user_id) DO NOTHING;
  UPDATE public.credits SET balance=balance+900,updated_at=at_utc
    WHERE user_id=target_user RETURNING balance INTO resulting_balance;
  GET DIAGNOSTICS written_rows=ROW_COUNT;
  IF written_rows<>1 OR resulting_balance<>900 THEN RAISE EXCEPTION 'gift_balance_mismatch'; END IF;
  INSERT INTO public.credit_transactions(id,user_id,type,amount,balance_after,description,
      paid_rmb,package_id,payment_ref,recorded_at)
    VALUES('4437ee15-a944-507c-8e22-89c79c6ad6d3',target_user,'gift',900,900,
      'owner-test-gift-20260907-900',0,'','',at_utc);
END
$owner_gift$;
COMMIT;
