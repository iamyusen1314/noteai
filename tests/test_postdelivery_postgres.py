"""Explicit disposable schema31 PG16; original App/Payment/Admin ACL only.

All supplier/payment transports are synthetic. This is financial consistency
and persistence validation, not real model, vendor, Linux or capacity acceptance.
"""
import asyncio
import json
import os
from pathlib import Path
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import urlencode

import api
import admin_entitlements
import billing
import db
import idempotency
import payment_contract
import postdelivery
import task_clarification
from tests import test_payment_contract as payment_fixtures
from tests import test_postdelivery_reservation as fixtures


@unittest.skipUnless(os.environ.get("NOTEAI_POSTDELIVERY_PG_TEST") == "1",
                     "explicit owned schema31 PG16 Unix socket required")
class PostDeliveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socket=Path(os.environ["NOTEAI_GENERATION_ACCOUNTING_PG_SOCKET"])
        cls.database=os.environ["NOTEAI_GENERATION_ACCOUNTING_PG_DATABASE"]
        assert socket.is_dir() and socket.parent.name.startswith("na-generation-pg16-")
        assert cls.database.startswith("noteai_generation_test_")
        cls.urls={role:"postgresql://"+role+"@/"+cls.database+"?"+urlencode({
            "host":str(socket),"port":"19432","connect_timeout":"5"})
            for role in ("noteai_app","noteai_payment","noteai_admin_runtime")}
        cls.env=mock.patch.dict(os.environ,{"DATABASE_URL":cls.urls["noteai_app"],
            "PYTHON_DOTENV_DISABLED":"1","NOTEAI_POSTDELIVERY_SETTLEMENT":"1",
            "NOTEAI_PUBLIC_PRODUCT":"0","NOTEAI_FACT_SEARCH":"0"})
        cls.env.start()
        for role,url in cls.urls.items():
            with mock.patch.dict(os.environ,{"DATABASE_URL":url}):
                row=db.fetchone("SELECT current_user AS role,current_database() AS db,"
                    "inet_server_addr() AS address,current_setting('listen_addresses') AS listeners,"
                    "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolinherit "
                    "FROM pg_roles WHERE rolname=current_user) AS privileged")
                assert row=={"role":role,"db":cls.database,"address":None,"listeners":"","privileged":False}

    @classmethod
    def tearDownClass(cls):
        billing.clear_active_usage();cls.env.stop()

    def setUp(self):
        self.user="postdelivery-pg-"+uuid.uuid4().hex;self.key=0
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",(self.user,self.user,self.user+"@example.invalid","fixture","fixture",billing._now()))
        billing.get_subscription(self.user);billing.clear_active_usage()

    def tearDown(self):billing.clear_active_usage()

    reserve=fixtures.PostDeliveryReservationTests.reserve
    use_wallet=fixtures.PostDeliveryReservationTests.use_wallet
    available=fixtures.PostDeliveryReservationTests.available
    wallet=fixtures.PostDeliveryReservationTests.wallet
    known_call=fixtures.PostDeliveryReservationTests.known_call
    save=fixtures.PostDeliveryReservationTests.save
    recovery_snapshot=fixtures.PostDeliveryReservationTests.recovery_snapshot

    def paid_order(self):
        fixture=payment_fixtures.PaymentContractTests()
        fixture.now=datetime.now(timezone.utc);fixture.app_id="app_test_001"
        _,order=fixture.create_order(user_id=self.user)
        with mock.patch.dict(os.environ,{"DATABASE_URL":self.urls["noteai_payment"]}):
            fixture.process(fixture.event(order,event_id="pg-payment-"+uuid.uuid4().hex,
                provider_payment_id="pg-payment-"+uuid.uuid4().hex))
            order=dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?",(order["id"],)))
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?",(self.user,))
        return fixture,order

    def test_real_app_role_ten_concurrent_claims_reserve_only_available_funds(self):
        self.use_wallet(16)
        def create(index):
            try:
                postdelivery.reserve_claim(user_id=self.user,operation="generate",request_id="pg-"+str(index),payload={})
                return "reserved"
            except Exception as exc:
                self.assertEqual(getattr(exc,"status_code",None),402)
                return "insufficient"
        with ThreadPoolExecutor(max_workers=10) as pool:states=list(pool.map(create,range(10)))
        self.assertEqual((states.count("reserved"),states.count("insufficient")),(2,8))
        self.assertEqual(self.wallet(),{"balance":16,"total_used":0})
        self.assertEqual(self.available()["wallet_held"],16)

    def test_original_paid_positions_consume_only_after_report_and_once(self):
        _,order=self.paid_order();claim=self.reserve();self.known_call(claim)
        self.assertEqual(db.fetchone("SELECT remaining_milli FROM payment_credit_positions WHERE order_id=?",(order["id"],))["remaining_milli"],30000)
        for _ in range(2):postdelivery.finalize_saved_result(claim,self.save(claim))
        self.assertEqual(self.wallet(),{"balance":22,"total_used":8})
        self.assertEqual(db.fetchone("SELECT count(*) AS n FROM payment_credit_consumptions WHERE usage_id=?",(claim["charge"]["usage_id"],))["n"],1)
        self.assertEqual(idempotency.read_failure_settlement(self.user,claim["request_id"])["refund_status"],"committed")

    def test_diagnosis_report_and_charge_rollback_then_commit_same_transaction(self):
        req=api.AnalyzeInput(note_title="原题",desc="原文",domain="休闲娱乐体验")
        claim=api._paid_request_claim("pg-diagnose-"+uuid.uuid4().hex,user_id=self.user,operation="analyze",payload=req)
        self.known_call(claim)
        response=api.AnalyzeResponse(ces_percentile=71,composite_score=71,grade="良好",features={},weaknesses=[],
            ai_diagnosis="模拟诊断",suggested_titles=["原题"],suggested_body="原文",improvement_plan="建议",model_used="synthetic")
        original=db.Transaction.execute
        def fail(tx,sql,*args):
            if sql.startswith("INSERT INTO saved_diagnoses"):raise RuntimeError("synthetic report failure")
            return original(tx,sql,*args)
        with mock.patch.object(db.Transaction,"execute",new=fail):
            with self.assertRaises(RuntimeError):api._persist_postdelivery_diagnosis(claim,response,{"id":self.user},req,"原文",False)
        self.assertEqual(db.fetchone("SELECT count(*) AS n FROM notes WHERE user_id=?",(self.user,))["n"],0)
        self.assertEqual(billing.get_quota_status(self.user)["monthly_credits_used"],0)
        with mock.patch.object(api._memory,"check_and_record_achievements"):
            api._persist_postdelivery_diagnosis(claim,response,{"id":self.user},req,"原文",False)
        reopened=asyncio.run(api.get_diagnosis(claim["request_id"],{"id":self.user}))
        self.assertEqual(reopened["billing"]["status"],"committed")
        self.assertEqual(billing.get_quota_status(self.user)["monthly_credits_used"],6)

    def test_expired_restart_release_preserves_physical_unknown_and_model_rows(self):
        self.use_wallet(8);claim=self.reserve();call=self.known_call(claim)
        db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(call,))
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ((idempotency._now()-timedelta(seconds=1)).isoformat(),claim["request_id"]))
        before=dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?",(call,)))
        snapshot,calls=self.recovery_snapshot(claim)
        for _ in range(2):postdelivery.reconcile_undelivered_reservation(self.user,claim["request_id"],
            expected_snapshot=snapshot,expected_provider_calls=calls,original_execution_ended=True)
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?",(call,))),before)
        self.assertEqual(self.wallet(),{"balance":8,"total_used":0})
        self.assertEqual(billing.get_quota_status(self.user)["wallet_credits_reserved"],0)

    def test_legacy_consumer_cannot_spend_reserved_monthly_allowance(self):
        self.reserve()
        with self.assertRaises(Exception) as error:
            idempotency.claim_and_charge(user_id=self.user,operation="generate",request_id="legacy-other",payload={})
        self.assertEqual(error.exception.status_code,402)
        claim=idempotency.claim_and_charge(user_id=self.user,operation="chat_rewrite",request_id="legacy-chat",payload={})
        self.assertEqual(claim["state"],"owner")
        self.assertEqual(billing.get_quota_status(self.user)["monthly_credits_used"],3)

    def test_payment_original_role_refund_guard_needs_no_idempotency_permission(self):
        _,order=self.paid_order();self.reserve()
        with mock.patch.dict(os.environ,{"DATABASE_URL":self.urls["noteai_payment"]}):
            allowed=db.fetchone("SELECT has_table_privilege(current_user,'idempotency_requests','SELECT') AS idem,"
                "has_column_privilege(current_user,'users','id','UPDATE') AS users_update")
            self.assertEqual(allowed,{"idem":False,"users_update":False})
            with self.assertRaisesRegex(payment_contract.PaymentContractError,"PAYMENT_ENTITLEMENT_RESERVED"):
                payment_contract.prepare_full_refund(order["id"],reason_code="service_not_delivered")
            self.assertEqual(db.fetchone("SELECT count(*) AS n FROM payment_refunds WHERE order_id=?",(order["id"],))["n"],0)

    def test_payment_callback_cash_truth_survives_reserved_entitlement_failure(self):
        fixture,order=self.paid_order()
        with mock.patch.dict(os.environ,{"DATABASE_URL":self.urls["noteai_payment"]}):
            prepared=payment_contract.prepare_full_refund(order["id"],reason_code="service_not_delivered")
            refund=dict(db.fetchone("SELECT * FROM payment_refunds WHERE id=?",(prepared["id"],)))
            payment_contract.mark_refund_submission(refund["id"],payment_contract.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],provider_refund_id="synthetic_refund",
                status="pending",amount_fen=refund["amount_fen"],response_verified=True))
        fetchone=db.Transaction.fetchone
        def legacy_read(tx,sql,*args):
            if sql.startswith("SELECT user_id FROM payment_orders WHERE user_id=? "):return None
            return fetchone(tx,sql,*args)
        with mock.patch.object(db.Transaction,"fetchone",new=legacy_read):self.reserve()
        with mock.patch.dict(os.environ,{"DATABASE_URL":self.urls["noteai_payment"]}):
            refund=dict(db.fetchone("SELECT * FROM payment_refunds WHERE id=?",(refund["id"],)))
            fixture.now=datetime.now(timezone.utc)+timedelta(seconds=1)
            fixture.process(fixture.refund_event(order,refund,event_id="pg-refund-"+uuid.uuid4().hex))
            cash=db.fetchone("SELECT count(*) AS n FROM payment_cash_ledger WHERE order_id=? AND entry_type='refund_paid'",(order["id"],))
            self.assertEqual(cash["n"],1)
            self.assertEqual(db.fetchone("SELECT refund_status FROM payment_orders WHERE id=?",(order["id"],))["refund_status"],"needs_manual")
        self.assertEqual(self.wallet(),{"balance":30,"total_used":0})
        self.assertEqual(self.available()["wallet_held"],8)

    def test_admin_original_role_rejects_negative_adjustment_but_allows_positive_gift(self):
        self.use_wallet(8);self.reserve()
        with mock.patch.dict(os.environ,{"DATABASE_URL":self.urls["noteai_admin_runtime"]}):
            with self.assertRaises(Exception) as error:
                admin_entitlements.preview(self.user,{"action":"adjust_credits","source":"gift","amount":-8})
            self.assertEqual(error.exception.status_code,409)
            preview=admin_entitlements.preview(self.user,{"action":"adjust_credits","source":"gift","amount":2})
            admin_entitlements.apply(self.user,preview["payload"],actor="noteai_admin",request_id=str(uuid.uuid4()),
                reason="isolated positive gift test",expected=preview["expected"])
        self.assertEqual(self.wallet(),{"balance":10,"total_used":0})
        self.assertEqual(self.available()["wallet_held"],8)

    def test_waiting_app_role_resume_and_cancel_share_original_user_fence(self):
        claim=self.reserve();self.known_call(claim)
        question={"field":"package_scope","question":"套餐包含门票吗？","source_quote":"双人套餐门票另有组合",
            "object":"双人套餐","time_range":"10月"}
        marker=task_clarification.execution.set({"claim":claim})
        try:
            with self.assertRaises(task_clarification.WaitingForInput) as paused:
                task_clarification.pause({"pipeline":"generate_stream","domain":"休闲娱乐体验","local_time":""},
                    [{"role":"内容专家","raw":"<clarifications>"+json.dumps([question],ensure_ascii=False)+"</clarifications>"}],
                    source="双人套餐门票另有组合")
        finally:task_clarification.execution.reset(marker)
        event=paused.exception.event
        def resume():
            try:
                return task_clarification.resume(self.user,claim["request_id"],event["version"],
                    [{"question_id":event["questions"][0]["question_id"],"status":"omitted"}])[0]
            except Exception as exc:
                self.assertEqual(exc.status_code,409);return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(resume);b=pool.submit(postdelivery.cancel_waiting_reservation,self.user,claim["request_id"])
            resumed,cancelled=a.result(),b.result()
        row=db.fetchone("SELECT status,refund_applied FROM idempotency_requests WHERE id=?",(claim["request_id"],))
        if resumed:
            self.assertIsNone(cancelled);self.assertEqual((row["status"],row["refund_applied"]),("running",0))
        else:
            self.assertEqual(cancelled["status"],"released");self.assertEqual((row["status"],row["refund_applied"]),("failed",1))
        self.assertEqual(billing.get_quota_status(self.user)["monthly_credits_used"],0)


if __name__=="__main__":unittest.main()
