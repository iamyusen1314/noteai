"""Local prototype tests and explicit legacy counterexamples, not release GO."""
import contextlib
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import billing
import db
import idempotency
import postdelivery as settlement
import public_product
from tests import test_payment_contract as payment_fixtures


class PostDeliveryReservationTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1"})
        self.env.start()
        self.old_db = db._DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "reservation.db"
        db.init_db()
        billing.clear_active_usage()
        self.user = "reservation-owner"
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)", (self.user,self.user,self.user+"@example.invalid","fixture","fixture",billing._now()))
        billing.get_subscription(self.user)
        self.key = 0

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db
        self.temp.cleanup()
        self.env.stop()

    def reserve(self, operation="generate", key=None):
        self.key += 1
        return settlement.reserve_claim(user_id=self.user,operation=operation,
            request_id=key or "reservation-"+str(self.key),payload={"fixture":True})

    def available(self):
        with db.transaction(write=True) as tx:
            sub = billing._get_subscription_tx(tx,self.user)
            return settlement.availability_in_transaction(tx,self.user,sub)

    def wallet(self):
        return dict(db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?",(self.user,)))

    def use_wallet(self, amount=16):
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?",(self.user,))
        billing.grant_credits(self.user,amount,"offline reservation fixture")

    def known_call(self, claim):
        import uuid
        call = str(uuid.uuid4())
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,"
            "created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",(call,public_product.BUDGET_ID,self.user,
            "fixture","dispatched",1,billing._now(),claim["charge"]["usage_id"]))
        billing.clear_active_usage()
        billing.record_model_usage("doubao","doubao-seed-2-0-lite-260428",tokens_in=100,
            tokens_out=10,usage_status="complete",physical_call_id=call)
        public_product._record_response(call,200)
        return call

    def save(self, claim, *, fail=False):
        def persist(tx):
            tx.execute("INSERT INTO notes(id,user_id,title,body,source,created_at) VALUES(?,?,?,?,?,?)",
                (claim["request_id"],self.user,"fixture title","fixture body",
                 "generate" if claim["operation"]=="generate" else "diagnose",billing._now()))
            if fail:
                raise RuntimeError("synthetic second persistence failure")
            result = {"saved_note_id":claim["request_id"]}
            if claim["operation"]=="analyze":
                tx.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) "
                    "VALUES(?,?,?,?,?,?)",(claim["request_id"],self.user,"fixture title","休闲娱乐体验",
                    '{"fixture":"saved"}',billing._now()))
                result["diagnosis_id"]=claim["request_id"]
            return result
        return persist

    def paid_wallet(self):
        fixture = payment_fixtures.PaymentContractTests()
        fixture.now = datetime.now(timezone.utc)
        fixture.app_id = "app_test_001"
        _order,row = fixture.create_order(user_id=self.user)
        _result,row = fixture.succeed_order(row)
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?",(self.user,))
        return row

    def test_admission_really_reserves_without_consumption_and_duplicate_is_durable(self):
        claim=self.reserve(key="same-key")
        duplicate=self.reserve(key="same-key")
        self.assertEqual((claim["state"],duplicate["state"]),("reservation_owner","in_progress"))
        row=db.fetchone("SELECT charge_source,charge_applied,complete_applied FROM idempotency_requests WHERE id=?",(claim["request_id"],))
        self.assertEqual(tuple(row),("reservation_v1:subscription:free",1,0))
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user,))[0],0)
        self.assertEqual(self.wallet(),{"balance":0,"total_used":0})
        self.assertEqual(self.available()["monthly_available"],4)
        self.assertEqual(db.fetchone("SELECT credits_used,source FROM usage_records WHERE id=?",(claim["charge"]["usage_id"],))[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records")[0],1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='usage'")[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM payment_credit_consumptions")[0],0)
        self.assertIsNone(db.fetchone("SELECT charged_at FROM idempotency_requests WHERE id=?",(claim["request_id"],))[0])
        self.assertFalse(idempotency.mark_completed(claim))
        self.assertTrue(idempotency.mark_failed_and_refund(claim,failure_code="stream_failed"))
        self.assertEqual(self.available()["monthly_held"],8)

    def test_two_of_ten_concurrent_claims_fit_wallet_and_survive_module_reload(self):
        self.use_wallet(16)
        def reserve(index):
            try:return settlement.reserve_claim(user_id=self.user,operation="generate",
                request_id="concurrent-"+str(index),payload={"fixture":True})["state"]
            except Exception as exc:
                self.assertEqual(getattr(exc,"status_code",None),402)
                return "insufficient"
        with ThreadPoolExecutor(max_workers=10) as pool:
            states=list(pool.map(reserve,range(10)))
        self.assertEqual((states.count("reservation_owner"),states.count("insufficient")),(2,8))
        importlib.reload(settlement)
        self.assertEqual((self.available()["wallet_available"],self.available()["wallet_held"]),(0,16))
        self.assertEqual(self.wallet(),{"balance":16,"total_used":0})

    def test_fixed_eight_consumed_once_only_with_saved_report_and_paid_fifo(self):
        order=self.paid_wallet()
        claim=self.reserve()
        self.assertEqual(db.fetchone("SELECT remaining_milli FROM payment_credit_positions WHERE order_id=?",(order["id"],))[0],30000)
        self.assertEqual(self.wallet(),{"balance":30,"total_used":0})
        self.known_call(claim)
        with mock.patch.dict(billing.OPERATIONS["generate"],{"credits":99}):
            first=settlement.finalize_saved_result(claim,self.save(claim))
        second=settlement.finalize_saved_result(claim,lambda tx:self.fail("repeated save"))
        self.assertEqual((first["credits_used"],second["credits_used"]),(8,8))
        self.assertEqual(self.wallet(),{"balance":22,"total_used":8})
        self.assertEqual(db.fetchone("SELECT remaining_milli FROM payment_credit_positions WHERE order_id=?",(order["id"],))[0],22000)
        self.assertEqual(db.fetchone("SELECT count(*) FROM payment_credit_consumptions")[0],1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='usage'")[0],1)
        settlement.assert_legacy_rollback_safe()

    def test_diagnosis_six_and_save_failure_rollback_is_atomic(self):
        claim=self.reserve(operation="analyze")
        self.known_call(claim)
        with self.assertRaisesRegex(RuntimeError,"persistence failure"):
            settlement.finalize_saved_result(claim,self.save(claim,fail=True))
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM saved_diagnoses")[0],0)
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user,))[0],0)
        self.assertEqual(self.available()["monthly_held"],6)
        settlement.finalize_saved_result(claim,self.save(claim))
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user,))[0],6)
        self.assertEqual(db.fetchone("SELECT count(*) FROM saved_diagnoses")[0],1)

    def test_commit_ack_unknown_reads_original_before_any_second_save_or_consumption(self):
        self.use_wallet(8)
        claim=self.reserve();self.known_call(claim)
        original=db.transaction
        @contextlib.contextmanager
        def committed_unknown(**kwargs):
            with original(**kwargs) as tx:
                yield tx
            raise RuntimeError("synthetic lost commit acknowledgement")
        with mock.patch.object(db,"transaction",new=committed_unknown):
            with self.assertRaisesRegex(RuntimeError,"commit acknowledgement"):
                settlement.finalize_saved_result(claim,self.save(claim))
        settlement.finalize_saved_result(claim,lambda tx:self.fail("unknown commit replayed"))
        self.assertEqual(self.wallet(),{"balance":0,"total_used":8})
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0],1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='usage'")[0],1)

    def test_failed_undelivered_release_does_not_refund_unspent_credits_or_supplier_cost(self):
        self.use_wallet(8)
        claim=self.reserve();call=self.known_call(claim)
        db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(call,))
        before=[dict(row) for row in db.fetchall("SELECT * FROM model_usage_records")]
        with self.assertRaises(ValueError):settlement.release_undelivered(claim,original_execution_ended=False)
        with self.assertRaises(ValueError):settlement.finalize_saved_result(claim,self.save(claim))
        with self.assertRaises(ValueError):settlement.assert_legacy_rollback_safe()
        for _ in range(2):settlement.release_undelivered(claim,original_execution_ended=True)
        self.assertEqual(self.wallet(),{"balance":8,"total_used":0})
        self.assertEqual(self.available()["wallet_available"],8)
        self.assertEqual([dict(row) for row in db.fetchall("SELECT * FROM model_usage_records")],before)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id=?",(call,))[0],"unknown")
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE type='refund'")[0],0)
        self.assertIsNone(db.fetchone("SELECT refunded_at FROM idempotency_requests WHERE id=?",(claim["request_id"],))[0])
        with db.transaction(write=False) as tx:
            # The old supplier UNKNOWN remains, but a released customer hold
            # does not ban a fresh, explicitly started same-media task.
            public_product._check_pending_media(tx,self.user,{"ref":"same","sha256":"same"})
        settlement.assert_legacy_rollback_safe()

    def test_waiting_same_claim_reserves_once_and_legacy_claim_stays_legacy(self):
        claim=self.reserve(key="waiting")
        db.execute("UPDATE idempotency_requests SET status='waiting_for_input' WHERE id=?",(claim["request_id"],))
        self.assertEqual(self.reserve(key="waiting")["state"],"waiting_for_input")
        self.assertEqual(self.available()["monthly_held"],8)
        db.execute("UPDATE idempotency_requests SET status='running' WHERE id=?",(claim["request_id"],))
        self.known_call(claim);settlement.finalize_saved_result(claim,self.save(claim))
        # An actual legacy claim is still handled by the old contract after capacity is provided.
        billing.grant_credits(self.user,8,"offline legacy fixture")
        legacy=idempotency.claim_and_charge(user_id=self.user,operation="generate",request_id="legacy",payload={"fixture":True})
        projection=self.reserve(key="legacy")
        self.assertEqual(projection["state"],"legacy_existing")
        self.assertEqual(legacy["state"],"owner")

    def test_cross_free_month_honors_old_period_without_consuming_new_allowance(self):
        old=datetime(2026,10,31,23,55,tzinfo=timezone.utc)
        new=old+timedelta(minutes=10)
        with mock.patch.object(billing,"_now",return_value=old.isoformat()),mock.patch.object(billing,"_month_start",return_value="2026-10-01T00:00:00+00:00"),mock.patch.object(idempotency,"_now",return_value=old):
            claim=self.reserve();self.known_call(claim)
        with mock.patch.object(billing,"_now",return_value=new.isoformat()),mock.patch.object(billing,"_month_start",return_value="2026-11-01T00:00:00+00:00"),mock.patch.object(idempotency,"_now",return_value=new):
            billing.get_subscription(self.user)
            self.assertEqual(self.available()["monthly_available"],12)
            settlement.finalize_saved_result(claim,self.save(claim))
            self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user,))[0],0)
            self.assertEqual(db.fetchone("SELECT charged_period_start FROM idempotency_requests WHERE id=?",(claim["request_id"],))[0],"2026-10-01T00:00:00+00:00")

    def test_legacy_spender_respects_hold_and_still_spends_unreserved_capacity(self):
        claim=self.reserve()
        with db.transaction(write=True) as tx:
            with self.assertRaises(ValueError):settlement.assert_legacy_spend_safe(tx,self.user)
        with self.assertRaises(Exception) as rejected:
            idempotency.claim_and_charge(user_id=self.user,operation="generate",request_id="old-bypass",payload={})
        self.assertEqual(rejected.exception.status_code,402)
        legacy=idempotency.claim_and_charge(user_id=self.user,operation="chat_rewrite",request_id="old-safe",payload={})
        self.assertEqual(legacy["state"],"owner")
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=?",(self.user,))[0],3)
        self.assertEqual(self.available()["monthly_held"],8)
        with self.assertRaises(ValueError):settlement.assert_legacy_rollback_safe()

    def test_legacy_direct_refund_cannot_mint_unspent_wallet(self):
        self.use_wallet(8);claim=self.reserve()
        with self.assertRaises(Exception) as rejected:
            billing.refund_operation_charge(self.user,"generate",claim["charge"],"offline counterexample")
        self.assertEqual(rejected.exception.status_code,409)
        self.assertEqual(self.wallet()["balance"],8)
        with self.assertRaises(ValueError):settlement.assert_legacy_rollback_safe()

    def test_cash_refund_eligibility_now_respects_hold(self):
        import payment_contract
        order=self.paid_wallet();self.reserve()
        with db.transaction(write=True) as tx:
            with self.assertRaises(ValueError):settlement.assert_entitlement_mutation_safe(tx,self.user)
        with self.assertRaisesRegex(payment_contract.PaymentContractError,"PAYMENT_ENTITLEMENT_RESERVED"):
            payment_contract.prepare_full_refund(order["id"],reason_code="service_not_delivered")
        self.assertEqual(db.fetchone("SELECT count(*) FROM payment_refunds")[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM payment_credit_consumptions")[0],0)

    def test_admin_negative_gift_now_respects_hold(self):
        import admin_entitlements
        self.use_wallet(8);self.reserve()
        with db.transaction(write=True) as tx:
            before=admin_entitlements.snapshot(tx,self.user)
            with self.assertRaises(Exception) as blocked:
                admin_entitlements.proposed(before,{"action":"adjust_credits","amount":-8})
            self.assertEqual(blocked.exception.status_code,409)
            with self.assertRaises(ValueError):settlement.assert_entitlement_mutation_safe(tx,self.user)
            self.assertEqual(admin_entitlements.proposed(before,
                {"action":"adjust_credits","amount":2})["wallet_balance"],10)
            with self.assertRaises(Exception):
                admin_entitlements.proposed(before,{"action":"set_membership","tier":"free"})

    def test_pending_cash_refund_cannot_acquire_new_reservation(self):
        import payment_contract
        order=self.paid_wallet()
        payment_contract.prepare_full_refund(order["id"],reason_code="service_not_delivered")
        with self.assertRaises(Exception) as blocked:self.reserve()
        self.assertEqual(blocked.exception.status_code,409)
        self.assertEqual(db.fetchone("SELECT count(*) FROM idempotency_requests")[0],0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM payment_credit_consumptions")[0],0)

    def test_actual_cash_callback_preserved_when_entitlement_is_now_reserved(self):
        import payment_contract
        order=self.paid_wallet()
        # Simulate the already submitted cash refund arriving after a legacy
        # process admitted work. No HTTP/payment is performed in this fixture.
        prepared=payment_contract.prepare_full_refund(order["id"],reason_code="service_not_delivered")
        refund=dict(db.fetchone("SELECT * FROM payment_refunds WHERE id=?",(prepared["id"],)))
        payment_contract.mark_refund_submission(refund["id"],payment_contract.ProviderRefundResult(
            merchant_refund_no=refund["merchant_refund_no"],provider_refund_id="synthetic_refund",
            status="pending",amount_fen=refund["amount_fen"],response_verified=True))
        # This bypass is fixture-only to reach the unavoidable external-cash
        # race; normal reservation admission above refuses pending refunds.
        fetchone=db.Transaction.fetchone
        def legacy_pending_read(tx,sql,*args):
            if sql.startswith("SELECT user_id FROM payment_orders WHERE user_id=? "):
                return None
            return fetchone(tx,sql,*args)
        with mock.patch.object(db.Transaction,"fetchone",new=legacy_pending_read):self.reserve()
        fixture=payment_fixtures.PaymentContractTests()
        fixture.now=datetime.now(timezone.utc);fixture.app_id="app_test_001"
        refund=dict(db.fetchone("SELECT * FROM payment_refunds WHERE id=?",(refund["id"],)))
        order=dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?",(order["id"],)))
        fixture.process(fixture.refund_event(order,refund))
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM payment_cash_ledger WHERE entry_type='refund_paid'")[0],1)
        self.assertEqual(db.fetchone("SELECT refund_status FROM payment_orders WHERE id=?",(order["id"],))[0],"needs_manual")
        self.assertEqual(self.wallet(),{"balance":30,"total_used":0})
        self.assertEqual(self.available()["wallet_held"],8)
        self.assertEqual(db.fetchone("SELECT remaining_milli FROM payment_credit_positions WHERE order_id=?",(order["id"],))[0],30000)

    def recovery_snapshot(self,claim):
        fields=("operation","key_hash","payload_hash","usage_id","lease_token_hash","lease_expires_at",
            "charge_source","credits_used","monthly_credits_used","wallet_credits_used",
            "charged_subscription_id","charged_period_start","status","failure_code","failed_at")
        row=dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?",(claim["request_id"],)))
        calls=[dict(row) for row in db.fetchall("SELECT id,state,http_status,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",(row["usage_id"],))]
        return {key:row[key] for key in fields},calls

    def test_restart_release_binds_complete_snapshot_and_preserves_supplier_unknown(self):
        self.use_wallet(8);claim=self.reserve();call=self.known_call(claim)
        db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(call,))
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ((idempotency._now()-timedelta(seconds=5)).isoformat(),claim["request_id"]))
        snapshot,calls=self.recovery_snapshot(claim)
        provider_before=[dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")]
        meter_before=[dict(row) for row in db.fetchall("SELECT * FROM model_usage_records")]
        args=dict(expected_snapshot=snapshot,expected_provider_calls=calls)
        with self.assertRaises(ValueError):settlement.reconcile_undelivered_reservation(
            self.user,claim["request_id"],original_execution_ended=False,**args)
        self.assertEqual(self.available()["wallet_held"],8)
        with self.assertRaisesRegex(ValueError,"manifest changed"):
            settlement.reconcile_undelivered_reservation(self.user,claim["request_id"],
                original_execution_ended=True,expected_snapshot=snapshot,expected_provider_calls=[])
        importlib.reload(settlement)  # No raw in-memory owner token is available.
        for _ in range(2):
            self.assertEqual(settlement.reconcile_undelivered_reservation(self.user,claim["request_id"],
                original_execution_ended=True,**args)["status"],"released")
        self.assertEqual(self.wallet(),{"balance":8,"total_used":0})
        self.assertEqual(self.available()["wallet_held"],0)
        self.assertEqual([dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")],provider_before)
        self.assertEqual([dict(row) for row in db.fetchall("SELECT * FROM model_usage_records")],meter_before)

    def test_restart_recovery_never_releases_waiting_live_or_saved_work(self):
        claim=self.reserve()
        snapshot,calls=self.recovery_snapshot(claim)
        with self.assertRaises(ValueError):settlement.reconcile_undelivered_reservation(
            self.user,claim["request_id"],expected_snapshot=snapshot,
            expected_provider_calls=calls,original_execution_ended=True)
        db.execute("UPDATE idempotency_requests SET status='waiting_for_input',lease_expires_at=? WHERE id=?",
            ((idempotency._now()-timedelta(seconds=5)).isoformat(),claim["request_id"]))
        snapshot,calls=self.recovery_snapshot(claim)
        with self.assertRaises(ValueError):settlement.reconcile_undelivered_reservation(
            self.user,claim["request_id"],expected_snapshot=snapshot,
            expected_provider_calls=calls,original_execution_ended=True)
        self.assertEqual(self.available()["monthly_held"],8)

    def test_ten_users_keep_nine_database_reservations_isolated_without_consumption(self):
        users=[]
        for index in range(10):
            uid="reservation-multiple-"+str(index)
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                "VALUES(?,?,?,?,?,?)",(uid,uid,uid+"@example.invalid","fixture","fixture",billing._now()))
            billing.grant_credits(uid,100,"offline multiuser database fixture")
            users.append(uid)
        def reserve_nine(uid):
            return [settlement.reserve_claim(user_id=uid,operation="generate",request_id=f"{uid}-{i}",
                payload={"fixture":True})["state"] for i in range(9)]
        with ThreadPoolExecutor(max_workers=10) as pool:
            self.assertEqual(list(pool.map(reserve_nine,users)),[["reservation_owner"]*9]*10)
        for uid in users:
            with db.transaction(write=True) as tx:
                sub=billing._get_subscription_tx(tx,uid)
                available=settlement.availability_in_transaction(tx,uid,sub)
                self.assertEqual((available["monthly_held"],available["wallet_held"],available["wallet_available"]),(12,60,40))
                self.assertEqual(tx.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?",(uid,))["balance"],100)
        self.assertEqual(db.fetchone("SELECT SUM(credits_used) FROM usage_records")[0],0)

    def test_concurrent_completion_and_release_cannot_both_apply(self):
        import threading
        self.use_wallet(16)
        claim=self.reserve();self.known_call(claim)
        began=threading.Event();allow_save=threading.Event()
        def persist(tx):
            began.set();self.assertTrue(allow_save.wait(2))
            return self.save(claim)(tx)
        def release():
            with self.assertRaises(ValueError):
                settlement.release_undelivered(claim,original_execution_ended=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            completed=pool.submit(settlement.finalize_saved_result,claim,persist)
            self.assertTrue(began.wait(2));released=pool.submit(release)
            allow_save.set();self.assertEqual(completed.result()["status"],"committed");released.result()
        self.assertEqual(self.wallet(),{"balance":8,"total_used":8})
        self.assertEqual(tuple(db.fetchone("SELECT complete_applied,refund_applied FROM idempotency_requests WHERE id=?",(claim["request_id"],))),(1,0))
        second=self.reserve();self.known_call(second)
        settlement.release_undelivered(second,original_execution_ended=True)
        with self.assertRaises(ValueError):settlement.finalize_saved_result(second,self.save(second))
        self.assertEqual(self.wallet(),{"balance":8,"total_used":8})

    def test_original_paid_period_can_finish_after_expiry_without_charging_new_free_period(self):
        old=datetime.now(timezone.utc)
        db.execute("UPDATE subscriptions SET tier='pro',expires_at=?,period_start=?,used_monthly_credits=0 WHERE user_id=?",
            ((old+timedelta(minutes=5)).isoformat(),old.isoformat(),self.user))
        with mock.patch.object(idempotency,"_now",return_value=old):
            claim=self.reserve();self.known_call(claim)
        later=old+timedelta(minutes=10)
        with mock.patch.object(billing,"_now",return_value=later.isoformat()),mock.patch.object(idempotency,"_now",return_value=later):
            fresh=billing.get_subscription(self.user)
            self.assertEqual(fresh["tier"],"free")
            settlement.finalize_saved_result(claim,self.save(claim))
        original=db.fetchone("SELECT used_monthly_credits,is_active FROM subscriptions WHERE id=?",(claim["charge"]["subscription_id"],))
        self.assertEqual(tuple(original),(8,0))
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE id=?",(fresh["id"],))[0],0)

    def test_unrecognized_reservation_metadata_and_unknown_saved_result_fail_closed(self):
        claim=self.reserve()
        db.execute("UPDATE idempotency_requests SET charge_source='reservation_v1:unknown:free' WHERE id=?",(claim["request_id"],))
        with self.assertRaises(ValueError):self.available()
        with self.assertRaises(ValueError):settlement.assert_legacy_rollback_safe()
        db.execute("UPDATE idempotency_requests SET charge_source='reservation_v1:subscription:free',failure_code='result_store_unknown' WHERE id=?",(claim["request_id"],))
        with self.assertRaises(ValueError):settlement.release_undelivered(claim,original_execution_ended=True)
        self.assertEqual(self.available()["monthly_held"],8)

    def test_finalization_rejects_legacy_backing_loss_instead_of_spending_other_holds(self):
        self.use_wallet(16)
        first=self.reserve();self.reserve();self.known_call(first)
        # A deliberately incompatible legacy mutation bypasses the guard.
        db.execute("UPDATE credits SET balance=10 WHERE user_id=?",(self.user,))
        with self.assertRaisesRegex(ValueError,"lost their backing"):
            settlement.finalize_saved_result(first,self.save(first))
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0],0)
        self.assertEqual(self.wallet(),{"balance":10,"total_used":0})

    def test_quote_receipt_and_usage_show_hold_separately_when_creation_is_disabled(self):
        claim=self.reserve()
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"1"}):
            quote=billing.get_operation_quote(self.user,"generate")
            self.assertEqual((quote["credits"],quote["charge_timing"],quote["can_afford"]),(8,"after_saved_report",False))
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"0"}):
            self.assertEqual(billing.get_quota_status(self.user)["monthly_credits_reserved"],8)
            receipt=billing.get_charge_receipt(self.user,"generate",claim["charge"],claim["request_id"])
            self.assertEqual((receipt["status"],receipt["credits_used"],receipt["reserved_credits"]),("reserved",0,8))
        usage=billing.get_usage_summary(self.user)
        detail=next(item for item in usage["recent_records"] if item["usage_id"]==claim["charge"]["usage_id"])
        self.assertEqual((detail["status"],detail["credits_used"],detail["monthly_credits_used"]),("reserved",0,0))
        self.known_call(claim);settlement.finalize_saved_result(claim,self.save(claim))
        receipt=billing.get_charge_receipt(self.user,"generate",claim["charge"],claim["request_id"])
        self.assertEqual((receipt["status"],receipt["credits_used"],receipt["reserved_credits"]),("committed",8,0))
        self.assertEqual(idempotency.read_failure_settlement(self.user,claim["request_id"])["refund_status"],"committed")

    def test_new_reservation_creation_is_opt_in_and_fixed_prices_stay_unchanged(self):
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"0"}):
            self.assertFalse(settlement.enabled())
            legacy_quote=billing.billing_quote_version()
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"1"}):
            reserved_quote=billing.billing_quote_version()
            with self.assertRaises(Exception) as changed:billing.assert_quote_version(legacy_quote)
            self.assertEqual(changed.exception.status_code,409)
        with mock.patch.dict(os.environ,{"NOTEAI_POSTDELIVERY_SETTLEMENT":"0"}):
            with self.assertRaises(Exception) as changed:billing.assert_quote_version(reserved_quote)
            self.assertEqual(changed.exception.status_code,409)
        self.assertEqual((billing.OPERATIONS["generate"]["credits"],billing.OPERATIONS["analyze"]["credits"]),(8,6))


if __name__=="__main__":unittest.main()
