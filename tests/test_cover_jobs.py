"""Targeted offline cover jobs, original ledger and private-image contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'model'))
from PIL import Image
from fastapi import HTTPException
import billing
import cover_jobs as jobs
import cover_renderer
import db
import postdelivery
import private_storage


class CoverJobsTests(unittest.TestCase):
    def setUp(self):
        self.env=mock.patch.dict(os.environ,{'DATABASE_URL':'','PYTHON_DOTENV_DISABLED':'1'})
        self.env.start()
        self.temp=tempfile.TemporaryDirectory()
        self.old_path=db._DB_PATH
        db._DB_PATH=Path(self.temp.name)/'cover.db'
        db.init_db()
        jobs.init_sqlite_schema()
        self.backend=private_storage.InMemoryObjectBackend()
        private_storage.configure_object_backend(self.backend,key_epoch='cover-offline-fixture')
        self.now=datetime.now(timezone.utc)
        self.user='cover-owner'
        self.other='cover-other'
        for user in (self.user,self.other):
            db.execute('INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)',
                (user,user,user+'@example.invalid','fixture','fixture',self.now.isoformat()))
            billing.get_subscription(user)
            billing.grant_credits(user,64,'offline fixture')
        self.report=str(uuid.uuid4())
        db.execute('INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)',
            (self.report,self.user,'真实门店','休闲娱乐体验','{"visual":"真实照片"}',self.now.isoformat()))
        self.source=self.image(self.user,small=True)
        self.policy={'enabled':True,'operation':'cover_generate','provider':'seedream','model_id':jobs.MODEL_ID,
            'width':1776,'height':2368,'credits':8,'retention_seconds':90*86400,'max_physical_calls':3,
            'max_image_calls':1,'budget_id':'noteai-xhs-cover-20261019-acceptance'}
        self.input={'note_title':'真实门店','note_body':'真实素材笔记','visual_advice':'保留门店主体'}
        self.index=0

    def tearDown(self):
        private_storage.reset_object_backend()
        billing.clear_active_usage()
        db._DB_PATH=self.old_path
        self.env.stop()
        self.temp.cleanup()

    def image(self,user,*,small=False,now=None):
        out=io.BytesIO()
        Image.new('RGB',(32,24) if small else (1776,2368),(44,88,111)).save(out,'PNG')
        return private_storage.store_media_bytes(user,purpose='image',content_type='image/png',payload=out.getvalue(),
            item_count=1,ttl_seconds=90*86400 if not small else 86400,lifecycle='cover_v1' if not small else 'temporary',now=now)

    def submit(self,*,key=None,**overrides):
        self.index+=1
        args={'user_id':self.user,'report_type':'analyze','report_id':self.report,'request_id':key or 'cover-'+str(self.index),
            'source_refs':[self.source.id],'input_snapshot':self.input,'policy_snapshot':self.policy,
            'quote_version':jobs.policy_quote_version(self.policy)}
        args.update(overrides)
        return jobs.submit_job(**args)

    def claim(self):
        result=self.submit()
        return result,jobs.claim_job(result['job_id'])

    def physical(self,claim,*,http=200,state='responded',call_id=None):
        call_id=call_id or str(uuid.uuid4())
        db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id,http_status) VALUES(?,?,?,?,?,?,?,?,?)',
            (call_id,'noteai-xhs-cover-20261019-acceptance',claim['user_id'],'fixture',state,600,self.now.isoformat(),claim['charge']['usage_id'],http))
        return call_id

    def image_call(self,claim,*,billed_images=1):
        call=self.physical(claim,http=None,state='dispatched')
        jobs.begin_image_call(claim,call_id=call,provider='seedream',model_id=jobs.MODEL_ID,input_images=1,
            width=1776,height=2368,pricing_snapshot={'output':'0.60'},estimated_cost='0.60',currency='CNY',price_version='fixture-v1')
        jobs.finish_image_call(claim,call,status='responded',output_images=1,billed_images=billed_images,http_status=200)
        db.execute("UPDATE public_trial_calls SET state='responded',http_status=200 WHERE id=?",(call,))
        return call

    def assets(self,*,text='真实门店',position='top',route='seedream_background'):
        _,source=private_storage.load_media_bytes(self.source.id,user_id=self.user,purpose='image')
        plan={'route':route,'source_ref':self.source.id,'crop':[0,0,1,1],'subject_bbox':[0,0,1,1],
            'photo_bbox':[.05,.30,.95,.95],'text_bbox':[.05,.05,.95,.25],'text':text,
            'font_size':96,'align':'center','background_color':'#FFFFFF','text_color':'#111111','panel_color':'#FFFFFF'}
        base,layout=cover_renderer.compose_base(source,plan)
        final,layout=cover_renderer.render_text(base,layout)
        def store(body):
            return private_storage.store_media_bytes(self.user,purpose='image',content_type='image/png',payload=body,
                item_count=1,ttl_seconds=90*86400,lifecycle='cover_v1')
        return store(final),store(base),layout

    def text_calls(self,claim):
        row=db.fetchone('SELECT call_intents_json FROM cover_jobs WHERE id=?',(claim['request_id'],))
        intents=json.loads(row['call_intents_json'])
        for stage in ('design','qc'):
            if stage in intents:continue
            call=str(uuid.uuid4())
            jobs.before_text_call(claim,stage,call)
            self.physical(claim,call_id=call)
            billing.record_model_usage('doubao','doubao-seed-2-0-lite-260428',tokens_in=100,tokens_out=10,
                usage_status='complete',physical_call_id=call)

    def complete(self,claim,**kwargs):
        self.text_calls(claim)
        final,base,layout=self.assets()
        result=jobs.complete_job(claim,final_media_ref=final.id,base_media_ref=base.id,
            layout=layout,qc_passed=True,**kwargs)
        return result,final,base

    def balances(self):
        row=db.fetchone('SELECT balance,total_used FROM credits WHERE user_id=?',(self.user,))
        sub=db.fetchone('SELECT used_monthly_credits FROM subscriptions WHERE user_id=?',(self.user,))
        return tuple(row),sub['used_monthly_credits']

    def test_quote_has_separate_cover_identity_and_frozen_policy(self):
        quote=jobs.quote_for_user(self.user,policy_snapshot=self.policy)
        self.assertEqual((quote['operation'],quote['credits'],quote['charge_timing']),('cover_generate',8.0,'after_saved_cover'))
        self.assertNotEqual(quote['quote_version'],billing.billing_quote_version())
        self.assertEqual(quote['quote_version'],jobs.policy_quote_version(self.policy))
        self.assertEqual(quote['unknown_release_seconds'],1800)

    def test_reserve_once_duplicate_conflict_and_readonly_reopen(self):
        before=self.balances()
        first=self.submit(key='same')
        repeated=self.submit(key='same')
        self.assertEqual(first['job_id'],repeated['job_id'])
        self.assertEqual(first['request_id'],'same')
        self.assertTrue(first['created']);self.assertFalse(repeated['created'])
        self.assertEqual(self.balances(),before)
        self.assertEqual(first['billing']['reserved_credits'],8)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records WHERE operation='cover_generate'")[0],1)
        with self.assertRaises(HTTPException) as conflict:
            self.submit(key='same',input_snapshot={'note_title':'changed'})
        self.assertEqual(conflict.exception.status_code,409)
        original_transaction=db.transaction
        def readonly(*,write=False):
            self.assertFalse(write)
            return original_transaction(write=False)
        with mock.patch.object(db,'transaction',side_effect=readonly),mock.patch.object(db,'execute',side_effect=AssertionError('read write')):
            self.assertEqual(jobs.get_job(self.user,first['job_id'])['job_id'],first['job_id'])
            self.assertEqual(len(jobs.list_report_jobs(self.user,'analyze',self.report)),1)
        self.assertEqual(self.balances(),before)

    def test_allocation_shared_with_original_report_reservations(self):
        db.execute('UPDATE credits SET balance=0 WHERE user_id=?',(self.user,))
        self.submit()
        with self.assertRaises(HTTPException) as error:
            postdelivery.reserve_claim(user_id=self.user,operation='generate',request_id='other-report',payload={'fixture':True})
        self.assertEqual(error.exception.status_code,402)
        self.assertEqual(db.fetchone('SELECT used_monthly_credits FROM subscriptions WHERE user_id=?',(self.user,))[0],0)

    def test_concurrent_same_key_one_job_and_unique_hold(self):
        args=dict(user_id=self.user,report_type='analyze',report_id=self.report,request_id='concurrent-same',
            source_refs=[self.source.id],input_snapshot=self.input,policy_snapshot=self.policy,
            quote_version=jobs.policy_quote_version(self.policy))
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows=list(pool.map(lambda _:jobs.submit_job(**args),range(6)))
        self.assertEqual(len({r['job_id'] for r in rows}),1)
        self.assertEqual(sum(r['created'] for r in rows),1)
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_jobs')[0],1)
        self.assertEqual(self.balances()[1],0)

    def test_other_owner_and_expired_or_absent_image_cannot_reserve(self):
        other=self.image(self.other,small=True)
        for overrides in ({'user_id':self.other},{'source_refs':[other.id]},{'source_refs':[str(uuid.uuid4())]}):
            with self.subTest(overrides=overrides),self.assertRaises((HTTPException,private_storage.PrivateStorageError)):
                self.submit(**overrides)
        expired=self.image(self.user,small=True,now=self.now-timedelta(days=2))
        with self.assertRaises(private_storage.PrivateStorageError):self.submit(source_refs=[expired.id])
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_jobs')[0],0)

    def test_generation_standalone_contract_is_actual_completed_report(self):
        rid=str(uuid.uuid4());stamp=self.now.isoformat()
        db.execute('INSERT INTO notes(id,user_id,title,body,source,created_at) VALUES(?,?,?,?,?,?)',(rid,self.user,'生成标题','生成正文','generate',stamp))
        db.execute("INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,lease_expires_at,complete_applied,created_at,updated_at) VALUES(?,?,'generate',?,?,'completed',?,?,1,?,?)",
            (rid,self.user,rid,'fixture','fixture',stamp,stamp,stamp))
        task={'operation':'generate','status':'completed','result':{'note_title':'生成标题','note_body':'生成正文','saved_note_id':rid}}
        db.execute('INSERT INTO chat_sessions(id,user_id,note_id,generate_ctx_json,messages_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (rid,self.user,rid,json.dumps({'task_continuation':task}),'[]',stamp,stamp))
        self.assertEqual(self.submit(report_type='generate',report_id=rid)['report_type'],'generate')
        db.execute("UPDATE idempotency_requests SET status='running',complete_applied=0 WHERE id=?",(rid,))
        with self.assertRaises(HTTPException):self.submit(report_type='generate',report_id=rid)

    def test_real_saved_png_then_unique_eight_settlement_and_free_revisions(self):
        _,claim=self.claim();call=self.image_call(claim)
        self.assertTrue(jobs.image_call_settled(db,call))
        saved,final,base=self.complete(claim)
        self.assertEqual((saved['status'],saved['billing']['credits_used']),('completed',8))
        self.assertEqual(self.balances(),((64,0),8))
        again=jobs.complete_job(claim,final_media_ref='not-a-ref',base_media_ref='not-a-ref',layout={},qc_passed=False)
        self.assertEqual(again['asset_revision'],1)
        adjusted,_,adjusted_layout=self.assets(text='更短的文字')
        changed=jobs.update_adjusted_asset(self.user,saved['job_id'],final_media_ref=adjusted.id,
            layout=adjusted_layout,expected_revision=1)
        self.assertEqual(changed['asset_revision'],2)
        self.assertEqual(changed['expires_at'],saved['expires_at'])
        self.assertEqual(jobs.asset_reference(self.user,saved['job_id'],revision=1),final.id)
        self.assertEqual(jobs.asset_reference(self.user,saved['job_id'],base=True),base.id)
        self.assertEqual(jobs.asset_reference(self.user,saved['job_id']),adjusted.id)
        self.assertEqual(self.balances(),((64,0),8))
        self.assertEqual(db.fetchone('SELECT count(*) FROM public_trial_calls')[0],3)
        another,_,another_layout=self.assets(text='另一次')
        with self.assertRaises(HTTPException) as conflict:
            jobs.update_adjusted_asset(self.user,saved['job_id'],final_media_ref=another.id,
                layout=another_layout,expected_revision=1)
        self.assertEqual(conflict.exception.status_code,409)
        with self.assertRaises(HTTPException):jobs.asset_reference(self.other,saved['job_id'])

    def test_image_cost_unknown_amount_is_not_unknown_result(self):
        _,claim=self.claim();call=self.image_call(claim)
        cost=db.fetchone('SELECT actual_cost,cost_status FROM cover_image_usage WHERE id=?',(call,))
        self.assertIsNone(cost['actual_cost']);self.assertEqual(cost['cost_status'],'estimated')
        self.complete(claim)
        self.assertEqual(jobs.get_job(self.user,claim['request_id'])['billing']['credits_used'],8)

    def test_missing_billed_count_does_not_fake_cost_settlement(self):
        _,claim=self.claim();call=self.image_call(claim,billed_images=None)
        self.assertFalse(jobs.image_call_settled(db,call))
        with self.assertRaises(ValueError):self.complete(claim)
        self.assertEqual(self.balances()[1],0)
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_asset_revisions')[0],0)

    def test_quality_or_invalid_storage_failure_never_charges(self):
        _,claim=self.claim();self.image_call(claim)
        with self.assertRaises(ValueError):
            jobs.complete_job(claim,final_media_ref=self.source.id,base_media_ref=self.source.id,
                layout={'text':'test','position':'top'},qc_passed=True)
        with self.assertRaises(ValueError):
            jobs.complete_job(claim,final_media_ref='invalid',base_media_ref='invalid',layout={},qc_passed=False)
        jobs.fail_job(claim,failure_code='cover_quality_failed')
        row=jobs.get_job(self.user,claim['request_id'])
        self.assertEqual((row['status'],row['billing']['status'],row['billing']['credits_used']),('failed','released',0))
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_image_usage')[0],1)

    def test_commit_ack_unknown_reads_original_and_does_not_charge_twice(self):
        _,claim=self.claim();self.image_call(claim)
        self.text_calls(claim)
        final,base,layout=self.assets()
        original=db.transaction
        @contextlib.contextmanager
        def lost_ack(**kwargs):
            with original(**kwargs) as tx:yield tx
            if kwargs.get('write'):raise RuntimeError('synthetic commit ACK lost')
        with mock.patch.object(db,'transaction',new=lost_ack):
            with self.assertRaisesRegex(RuntimeError,'ACK lost'):
                jobs.complete_job(claim,final_media_ref=final.id,base_media_ref=base.id,
                    layout=layout,qc_passed=True)
        result=jobs.complete_job(claim,final_media_ref=final.id,base_media_ref=base.id,
            layout=layout,qc_passed=True)
        self.assertEqual(result['billing']['credits_used'],8)
        self.assertEqual(self.balances()[1],8)
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_asset_revisions')[0],1)

    def test_unknown_thirty_minute_release_preserves_cost_and_blocks_late_charge(self):
        _,claim=self.claim();call=self.physical(claim,state='dispatched',http=None)
        jobs.begin_image_call(claim,call_id=call,provider='seedream',model_id=jobs.MODEL_ID,input_images=1,
            width=1776,height=2368,pricing_snapshot={'output':'0.60'},estimated_cost='0.60',price_version='fixture-v1')
        jobs.finish_image_call(claim,call,status='unknown')
        db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(call,))
        jobs.fail_job(claim,failure_code='cover_provider_unknown',outcome_unknown=True)
        before=dict(db.fetchone('SELECT * FROM cover_image_usage WHERE id=?',(call,)))
        self.assertEqual(jobs.release_expired_unknowns(now=self.now+timedelta(minutes=29)),0)
        self.assertEqual(jobs.release_expired_unknowns(now=self.now+timedelta(minutes=31)),1)
        self.assertEqual(jobs.release_expired_unknowns(now=self.now+timedelta(minutes=32)),0)
        state=jobs.get_job(self.user,claim['request_id'])
        self.assertEqual((state['status'],state['billing']['status']),('outcome_unknown','released'))
        self.assertEqual(dict(db.fetchone('SELECT * FROM cover_image_usage WHERE id=?',(call,))),before)
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls WHERE id=?',(call,))[0],'unknown')
        with self.assertRaises(ValueError):self.complete(claim)
        self.assertEqual(self.balances()[1],0)
        self.assertIsNone(jobs.claim_job(claim['request_id']))

    def test_recovery_only_resumes_original_unstarted_task(self):
        first,claim=self.claim()
        db.execute('UPDATE cover_jobs SET lease_expires_at=? WHERE id=?',((self.now-timedelta(seconds=1)).isoformat(),first['job_id']))
        self.assertEqual(jobs.recover_jobs(),[first['job_id']])
        new=jobs.claim_job(first['job_id'])
        self.assertGreater(new['cover_fence'],claim['cover_fence'])
        with self.assertRaises(ValueError):jobs.mark_stage(claim,'image')
        jobs.before_text_call(new,'design',str(uuid.uuid4()))
        db.execute('UPDATE cover_jobs SET lease_expires_at=? WHERE id=?',((self.now-timedelta(seconds=1)).isoformat(),first['job_id']))
        self.assertEqual(jobs.recover_jobs(),[])
        self.assertEqual(jobs.get_job(self.user,first['job_id'])['status'],'outcome_unknown')
        self.assertIsNone(jobs.claim_job(first['job_id']))

    def test_fail_new_task_preserves_last_success_for_same_report(self):
        original,claim=self.claim();self.image_call(claim);self.complete(claim)
        second,new=self.claim();jobs.fail_job(new,failure_code='cover_local_invalid')
        rows=jobs.list_report_jobs(self.user,'analyze',self.report)
        self.assertEqual(len(rows),2)
        self.assertTrue(next(row for row in rows if row['job_id']==original['job_id'])['has_final'])
        self.assertFalse(next(row for row in rows if row['job_id']==second['job_id'])['has_final'])
        self.assertEqual(self.balances()[1],8)

    def test_paid_image_call_has_no_automatic_second_attempt(self):
        _,claim=self.claim();call=self.physical(claim,state='dispatched',http=None)
        kwargs=dict(provider='seedream',model_id=jobs.MODEL_ID,input_images=1,width=1776,height=2368,
            pricing_snapshot={'output':'0.60'},estimated_cost='0.60',price_version='fixture-v1')
        jobs.begin_image_call(claim,call_id=call,**kwargs)
        with self.assertRaises(ValueError):jobs.begin_image_call(claim,call_id=call,**kwargs)
        other=self.physical(claim,state='dispatched',http=None)
        with self.assertRaises(ValueError):jobs.begin_image_call(claim,call_id=other,**kwargs)
        jobs.finish_image_call(claim,call,status='unknown')
        self.assertFalse(jobs.finish_image_call(claim,call,status='unknown'))
        with self.assertRaises(ValueError):jobs.finish_image_call(claim,call,status='responded',output_images=1,billed_images=1,http_status=200)

    def test_nine_original_sources_are_frozen_with_verified_hashes(self):
        sources=[self.image(self.user,small=True) for _ in range(9)]
        result=self.submit(source_refs=[source.id for source in sources])
        row=db.fetchone('SELECT source_manifest_json,input_json FROM cover_jobs WHERE id=?',(result['job_id'],))
        manifest=json.loads(row['source_manifest_json'])
        self.assertEqual([item['media_ref'] for item in manifest],[source.id for source in sources])
        self.assertEqual([item['sha256'] for item in manifest],[source.content_sha256 for source in sources])
        self.assertEqual(json.loads(row['input_json']),self.input)
        self.assertEqual(self.balances()[1],0)

    def test_six_sample_bound_serializes_different_users_and_preserves_old_budget(self):
        other_report=str(uuid.uuid4())
        db.execute('INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)',
            (other_report,self.other,'另一门店','美食','{}',self.now.isoformat()))
        other_source=self.image(self.other,small=True)
        old=dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id='website-free-product-20260912'"))
        def run(index):
            user,report,source=(self.user,self.report,self.source) if index%2 else (self.other,other_report,other_source)
            try:
                result=jobs.submit_job(user_id=user,report_type='analyze',report_id=report,request_id='batch-'+str(index),
                    source_refs=[source.id],input_snapshot=self.input,policy_snapshot=self.policy,quote_version=jobs.policy_quote_version(self.policy))
                return result['created']
            except HTTPException as exc:
                self.assertEqual(exc.status_code,429)
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(run,range(12)))
        self.assertEqual(sum(rows),6)
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_jobs')[0],6)
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id='website-free-product-20260912'")),old)

    def test_asset_persistence_and_settlement_roll_back_together(self):
        _,claim=self.claim();self.image_call(claim);self.text_calls(claim)
        final,base,layout=self.assets()
        with mock.patch.object(postdelivery,'finalize_in_transaction',side_effect=RuntimeError('synthetic save transaction failed')):
            with self.assertRaisesRegex(RuntimeError,'save transaction failed'):
                jobs.complete_job(claim,final_media_ref=final.id,base_media_ref=base.id,layout=layout,qc_passed=True)
        row=db.fetchone('SELECT status,final_media_ref,asset_revision FROM cover_jobs WHERE id=?',(claim['request_id'],))
        self.assertEqual(tuple(row),('running',None,0))
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_asset_revisions')[0],0)
        self.assertEqual(jobs.get_job(self.user,claim['request_id'])['billing']['status'],'reserved')
        self.assertEqual(self.balances()[1],0)

    def test_cover_wallet_settlement_uses_one_original_debit(self):
        db.execute('UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?',(self.user,))
        _,claim=self.claim();self.image_call(claim);self.complete(claim)
        self.assertEqual(self.balances(),((56,8),12))
        self.assertEqual(db.fetchone("SELECT count(*) FROM credit_transactions WHERE user_id=? AND type='usage'",(self.user,))[0],1)
        self.assertEqual(db.fetchone('SELECT credits_used FROM usage_records WHERE id=?',(claim['charge']['usage_id'],))[0],8)

    def test_no_saved_cover_without_original_design_and_quality_calls(self):
        _,claim=self.claim();self.image_call(claim)
        final,base,layout=self.assets()
        with self.assertRaisesRegex(ValueError,'design and quality'):
            jobs.complete_job(claim,final_media_ref=final.id,base_media_ref=base.id,layout=layout,qc_passed=True)
        self.assertEqual(self.balances()[1],0)

    def test_saved_cover_is_discoverable_after_report_expiry_or_deletion(self):
        saved,claim=self.claim();self.image_call(claim);self.complete(claim)
        far_future=self.now+timedelta(days=8)
        with mock.patch('content_retention._now',return_value=far_future):
            listed=jobs.list_report_jobs(self.user,'analyze',self.report)
            self.assertEqual([row['job_id'] for row in listed],[saved['job_id']])
            with self.assertRaises(HTTPException):self.submit()
        db.execute('DELETE FROM saved_diagnoses WHERE id=?',(self.report,))
        self.assertEqual(len(jobs.list_report_jobs(self.user,'analyze',self.report)),1)
        with self.assertRaises(HTTPException):self.submit()
        self.assertEqual([row['job_id'] for row in jobs.list_user_jobs(self.user)],[saved['job_id']])
        self.assertEqual(jobs.list_user_jobs(self.other),[])
        self.assertEqual(jobs.list_user_jobs(self.user,now=self.now+timedelta(days=91)),[])
        self.assertEqual(jobs.asset_reference(self.user,saved['job_id']),db.fetchone('SELECT final_media_ref FROM cover_jobs WHERE id=?',(saved['job_id'],))[0])
        for invalid in (0,101,True):
            with self.assertRaises(HTTPException):jobs.list_user_jobs(self.user,limit=invalid)

    def test_late_supplier_bill_reconciles_without_rewriting_unknown_or_customer_charge(self):
        _,claim=self.claim();call=self.physical(claim,state='dispatched',http=None)
        jobs.begin_image_call(claim,call_id=call,provider='seedream',model_id=jobs.MODEL_ID,input_images=1,
            width=1776,height=2368,pricing_snapshot={'output':'0.60'},estimated_cost='0.60',price_version='fixture-v1')
        jobs.finish_image_call(claim,call,status='unknown')
        db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(call,))
        jobs.fail_job(claim,failure_code='cover_provider_unknown',outcome_unknown=True)
        jobs.release_expired_unknowns(now=self.now+timedelta(minutes=31))
        financial=dict(db.fetchone('SELECT * FROM idempotency_requests WHERE id=?',(claim['request_id'],)))
        usage=dict(db.fetchone('SELECT * FROM usage_records WHERE id=?',(claim['charge']['usage_id'],)))
        kwargs=dict(actual_cost='0.59',billed_images=1,evidence_ref='original-fixture-bill-1',currency='CNY')
        self.assertTrue(jobs.reconcile_image_cost(self.user,claim['request_id'],call,**kwargs))
        self.assertFalse(jobs.reconcile_image_cost(self.user,claim['request_id'],call,**kwargs))
        cost=db.fetchone('SELECT * FROM cover_image_usage WHERE id=?',(call,))
        self.assertEqual((cost['state'],cost['cost_status'],cost['actual_cost'],cost['billed_images']),('unknown','billed','0.59',1))
        self.assertIsNotNone(cost['cost_reconciled_at'])
        self.assertFalse(jobs.image_call_settled(db,call))
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls WHERE id=?',(call,))[0],'unknown')
        self.assertEqual(dict(db.fetchone('SELECT * FROM idempotency_requests WHERE id=?',(claim['request_id'],))),financial)
        after=dict(db.fetchone('SELECT * FROM usage_records WHERE id=?',(claim['charge']['usage_id'],)))
        for field in ('user_id','operation','credits_used','source','recorded_at'):
            self.assertEqual(after[field],usage[field])
        self.assertEqual(after['actual_model_cost_rmb'],0.59)
        self.assertEqual(self.balances()[1],0)
        for patch in ({'actual_cost':'0.60'},{'evidence_ref':'different-bill'},{'billed_images':0},{'currency':'USD'}):
            with self.subTest(patch=patch),self.assertRaises(HTTPException) as conflict:
                jobs.reconcile_image_cost(self.user,claim['request_id'],call,**{**kwargs,**patch})
            self.assertEqual(conflict.exception.status_code,409)
        # A second expiry scan cannot keep rewriting already released UNKNOWN.
        with mock.patch.object(db,'transaction',side_effect=AssertionError('unnecessary released task write')):
            self.assertEqual(jobs.release_expired_unknowns(now=self.now+timedelta(minutes=32)),0)

    def test_cover_parent_includes_image_call_without_falsely_exact_image_price(self):
        _,claim=self.claim();call=self.image_call(claim);self.text_calls(claim)
        token=float(db.fetchone('SELECT sum(known_cost_rmb) FROM model_usage_records WHERE usage_record_id=?',(claim['charge']['usage_id'],))[0])
        before=db.fetchone('SELECT actual_model_cost_rmb,estimated_cost_rmb,cost_mode,model_calls FROM usage_records WHERE id=?',(claim['charge']['usage_id'],))
        self.assertAlmostEqual(before['actual_model_cost_rmb'],token)
        self.assertAlmostEqual(before['estimated_cost_rmb'],token+0.60)
        self.assertEqual((before['cost_mode'],before['model_calls']),('partial',3))
        self.complete(claim)
        row=db.fetchone('SELECT actual_model_cost_rmb,cost_mode,model_calls FROM usage_records WHERE id=?',(claim['charge']['usage_id'],))
        self.assertEqual((row['cost_mode'],row['model_calls']),('partial',3))
        history=billing.get_usage_summary(self.user)
        record=next(r for r in history['recent_records'] if r['usage_id']==claim['charge']['usage_id'])
        self.assertEqual(record['image_usage']['physical_calls'],1)
        self.assertEqual(record['image_usage']['estimated_cost_rmb'],0.60)
        self.assertIsNone(record['image_usage']['actual_cost_rmb'])
        self.assertEqual(record['model_cost_status'],'partial')
        self.assertEqual(history['cover_image_usage']['unconfirmed_bills'],1)
        self.assertEqual(record['image_usage']['calls'][0]['pixel_count'],1776*2368)
        jobs.reconcile_image_cost(self.user,claim['request_id'],call,actual_cost='0.59',evidence_ref='fixture-original-bill',billed_images=1)
        billed=db.fetchone('SELECT actual_model_cost_rmb,cost_rmb,cost_mode,credits_used FROM usage_records WHERE id=?',(claim['charge']['usage_id'],))
        self.assertAlmostEqual(billed['actual_model_cost_rmb'],token+0.59)
        self.assertAlmostEqual(billed['cost_rmb'],token+0.59)
        self.assertEqual((billed['cost_mode'],billed['credits_used']),('actual',8))
        self.assertEqual(billing.get_usage_summary(self.user)['cover_image_usage']['actual_cost_rmb'],0.59)

    def test_deleting_user_does_not_block_other_original_job_recovery(self):
        first,claim=self.claim()
        report=str(uuid.uuid4())
        db.execute('INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)',
            (report,self.other,'另一门店','美食','{}',self.now.isoformat()))
        source=self.image(self.other,small=True)
        second=self.submit(user_id=self.other,report_id=report,source_refs=[source.id])
        other_claim=jobs.claim_job(second['job_id'])
        old=(self.now-timedelta(seconds=1)).isoformat()
        db.execute('UPDATE cover_jobs SET lease_expires_at=?',(old,))
        db.execute('UPDATE users SET deletion_requested_at=? WHERE id=?',(self.now.isoformat(),self.user))
        self.assertEqual(jobs.recover_jobs(),[second['job_id']])
        self.assertEqual(jobs.get_job(self.user,first['job_id'])['status'],'running')
        self.assertIsNone(jobs.claim_job(first['job_id']))
        self.assertEqual(jobs.release_expired_unknowns(now=self.now+timedelta(minutes=31)),1)
        self.assertEqual(jobs.get_job(self.other,second['job_id'])['billing']['status'],'released')
        self.assertEqual(db.fetchone('SELECT refund_applied FROM idempotency_requests WHERE id=?',(first['job_id'],))[0],0)

    def test_formal_scope_has_no_acceptance_sample_cap_and_does_not_borrow_test_budget(self):
        acceptance_before=dict(db.fetchone('SELECT * FROM public_trial_budget WHERE id=?',(jobs.BUDGET_ID,)))
        original_before=dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id='website-free-product-20260912'"))
        policy={**self.policy,'budget_id':jobs.FORMAL_BUDGET_ID}
        rows=[self.submit(policy_snapshot=policy,quote_version=jobs.policy_quote_version(policy)) for _ in range(7)]
        self.assertEqual(len(rows),7)
        self.assertEqual(db.fetchone('SELECT count(*) FROM cover_jobs WHERE budget_id=?',(jobs.FORMAL_BUDGET_ID,))[0],7)
        self.assertEqual(dict(db.fetchone('SELECT * FROM public_trial_budget WHERE id=?',(jobs.BUDGET_ID,))),acceptance_before)
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id='website-free-product-20260912'")),original_before)
        self.assertEqual(db.fetchone('SELECT count(*) FROM public_trial_calls')[0],0)
        self.assertEqual(self.balances()[0][1],0)
        for invalid in ('website-free-product-20260912','unknown-budget'):
            with self.assertRaises(ValueError):jobs.policy_quote_version({**policy,'budget_id':invalid})

    def test_public_position_options_exclude_moves_over_real_subject(self):
        projected=jobs._public_layout({'text':'真实门店','text_bbox':[.05,.05,.95,.25],
            'photo_bbox':[.05,.30,.95,.95],'rendered_lines':['真实门店'],'source_sha256':'PRIVATE-HASH'})
        self.assertEqual(projected['position_options'],['top'])
        self.assertEqual(projected['position'],'top')
        self.assertNotIn('source_sha256',projected)
        opposite=jobs._public_layout({'text':'真实门店','text_bbox':[.05,.75,.95,.95],
            'photo_bbox':[.05,.05,.95,.70]})
        self.assertEqual(opposite['position_options'],['bottom'])


if __name__=='__main__':unittest.main()
