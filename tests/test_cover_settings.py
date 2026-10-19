"""Offline configuration/price visibility tests; no provider or production work."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'model'))
from PIL import Image
from fastapi import HTTPException
import ark_media
import billing
import cover_jobs
import cover_settings as settings
import db
import private_storage


class CoverSettingsTests(unittest.TestCase):
    def setUp(self):
        self.env=mock.patch.dict(os.environ,{'DATABASE_URL':'','PYTHON_DOTENV_DISABLED':'1','NOTEAI_COVER_WORKER_ENABLED':'0'})
        self.env.start()
        self.temp=tempfile.TemporaryDirectory()
        self.old_path=db._DB_PATH
        db._DB_PATH=Path(self.temp.name)/'cover-settings.db'
        db.init_db()
        cover_jobs.init_sqlite_schema()
        self.backend=private_storage.InMemoryObjectBackend()
        private_storage.configure_object_backend(self.backend,key_epoch='settings-offline-fixture')
        self.provider=mock.patch.object(ark_media,'_complete_admitted',side_effect=AssertionError('settings called a provider'))
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        private_storage.reset_object_backend()
        billing.clear_active_usage()
        db._DB_PATH=self.old_path
        self.env.stop()
        self.temp.cleanup()

    def config(self,*,enabled=True,execution_scope='acceptance'):
        return {**settings.defaults(),'enabled':enabled,'execution_scope':execution_scope,
                'account_verified':True,'account_evidence_ref':'fixture-account-evidence-v1'}

    def change(self,action,*,scope='test',expected=0,config=None,request_id=None):
        return settings.change(action,scope,actor='noteai_admin',request_id=request_id or str(uuid.uuid4()),
            reason='隔离封面设置测试',expected=expected,config=config)

    def activate(self,*,scope='production',execution_scope='acceptance'):
        config=self.config(execution_scope=execution_scope)
        self.change('draft',scope=scope,expected=0,config=config)
        self.change('activate',scope=scope,expected=1)
        return config

    def test_default_disabled_and_read_view_have_no_ddl_or_writes(self):
        original=db.fetchone
        observed=[]
        def read(sql,params=()):
            observed.append(sql)
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
            return original(sql,params)
        with mock.patch.object(db,'fetchone',side_effect=read), \
             mock.patch.object(db,'execute',side_effect=AssertionError('read wrote SQL')), \
             mock.patch.object(db,'init_db',side_effect=AssertionError('read initialized schema')), \
             mock.patch.object(cover_jobs,'init_sqlite_schema',side_effect=AssertionError('read installed feature')), \
             mock.patch.object(ark_media,'configured',return_value=False):
            state=settings.read()
            view=settings.view()
        self.assertFalse(state['active']['enabled'])
        self.assertEqual((state['revision'],state['active_revision']),(0,0))
        self.assertEqual(view['budget']['scope'],'acceptance')
        self.assertEqual(view['budget']['limit_cny'],100)
        self.assertFalse(view['credential_configured'])
        self.assertGreaterEqual(len(observed),2)
        self.assertEqual(db.fetchone("SELECT count(*) FROM system_settings WHERE key LIKE 'noteai_cover_config_v1%'")[0],0)

    def test_validate_preserves_fixed_model_size_credits_ttl_and_call_contract(self):
        original=self.config()
        self.assertEqual(settings.validate(original),original)
        copied=settings.validate(original)
        copied['credits']=999
        self.assertEqual(original['credits'],8)
        for field,value in (('model_id','doubao-seedream-latest'),('design_model','unapproved-model'),
                            ('width',1024),('height',1024),('credits',4),('credits',8.0),
                            ('retention_seconds',86400),('max_physical_calls',4),('max_image_calls',2),
                            ('unknown_release_seconds',3600),('text_max_tokens',9999),
                            ('enabled','1'),('account_verified',1),('execution_scope','unknown'),
                            ('execution_scope',[]),('execution_scope',{})):
            with self.subTest(field=field,value=value):
                with self.assertRaises(HTTPException) as denied:
                    settings.validate({**original,field:value})
                self.assertEqual(denied.exception.status_code,422)
        for malformed in ({'enabled':False},{**original,'extra_flag':True}):
            with self.assertRaises(HTTPException):settings.validate(malformed)
        for evidence in ('Bearer fixture','fixture?credential=bad',' fixture ','line\nbreak'):
            with self.assertRaises(HTTPException):settings.validate({**original,'account_evidence_ref':evidence})
        with self.assertRaises(HTTPException) as no_account:
            settings.validate({**original,'account_verified':False})
        self.assertEqual(no_account.exception.status_code,409)

    def test_draft_activate_restore_replays_one_operation_and_checks_revision(self):
        config=self.config()
        request=str(uuid.uuid4())
        first=self.change('draft',config=config,request_id=request)
        repeated=self.change('draft',config=config,request_id=request)
        self.assertFalse(first['replayed']);self.assertTrue(repeated['replayed'])
        self.assertEqual(settings.read('test')['revision'],1)
        self.assertFalse(settings.read('test')['active']['enabled'])
        self.assertEqual(db.fetchone('SELECT count(*) FROM admin_operations')[0],1)
        with self.assertRaises(HTTPException) as changed_binding:
            self.change('draft',config={**config,'account_evidence_ref':'different-evidence'},request_id=request)
        self.assertEqual(changed_binding.exception.status_code,409)
        activation=self.change('activate',expected=1)
        self.assertTrue(activation['after']['active']['enabled'])
        self.assertEqual(settings.read('test')['active_revision'],2)
        next_config={**config,'execution_scope':'formal','account_evidence_ref':'fixture-account-evidence-v2'}
        self.change('draft',expected=2,config=next_config)
        self.change('activate',expected=3)
        self.assertEqual(settings.read('test')['active']['execution_scope'],'formal')
        restored=self.change('restore',expected=4)
        self.assertEqual(restored['after']['active'],config)
        self.assertEqual(restored['after']['active_revision'],5)
        with self.assertRaises(HTTPException) as stale:
            self.change('draft',expected=4,config=config)
        self.assertEqual(stale.exception.status_code,409)
        self.assertEqual(settings.read('test')['revision'],5)
        with self.assertRaises(HTTPException):self.change('activate',expected=5)
        with self.assertRaises(HTTPException):self.change('draft',config=config,request_id='not-a-uuid')

    def test_test_scope_does_not_activate_or_mutate_production(self):
        self.activate(scope='test')
        self.assertTrue(settings.read('test')['active']['enabled'])
        self.assertEqual(settings.read()['revision'],0)
        self.assertFalse(settings.read()['active']['enabled'])
        self.assertEqual(settings.read()['active']['execution_scope'],'acceptance')
        with self.assertRaises(HTTPException):settings.read('unknown')

    def test_policy_and_budget_display_keep_acceptance_limits_out_of_formal_scope(self):
        acceptance=settings.policy_snapshot(self.config())
        formal=settings.policy_snapshot(self.config(execution_scope='formal'))
        self.assertEqual(acceptance['budget_id'],settings.BUDGET_ID)
        self.assertEqual(formal['budget_id'],settings.FORMAL_BUDGET_ID)
        for policy in (acceptance,formal):
            self.assertEqual(policy['credits'],'8')
            self.assertEqual(policy['model_id'],settings.MODEL_ID)
            self.assertEqual((policy['width'],policy['height']),(1776,2368))
            self.assertEqual(policy['retention_seconds'],90*86400)
            self.assertEqual(policy['price_status'],'public_estimate')
            self.assertNotIn('actual_cost',policy)
        self.activate(scope='test',execution_scope='formal')
        view=settings.view('test')
        self.assertEqual(view['budget']['scope'],'formal')
        self.assertEqual(view['budget']['id'],settings.FORMAL_BUDGET_ID)
        for field in ('limit_cny','max_jobs','max_calls'):self.assertIsNone(view['budget'][field])
        self.assertEqual(view['budget']['automatic_paid_retries'],0)
        self.assertEqual(settings.view()['budget']['max_jobs'],6)

    def test_readiness_fails_closed_for_account_worker_credentials_storage_or_budget(self):
        self.assertFalse(settings.readiness()[0])
        self.activate()
        self.assertIn('执行',settings.readiness()[1])
        with mock.patch.dict(os.environ,{'NOTEAI_COVER_WORKER_ENABLED':'1'}), \
             mock.patch.object(ark_media,'configured',return_value=False):
            self.assertIn('模型',settings.readiness()[1])
        with mock.patch.dict(os.environ,{'NOTEAI_COVER_WORKER_ENABLED':'1'}), \
             mock.patch.object(ark_media,'configured',return_value=True), \
             mock.patch.object(private_storage,'object_backend_configured',return_value=False):
            self.assertIn('存储',settings.readiness()[1])
        with mock.patch.dict(os.environ,{'NOTEAI_COVER_WORKER_ENABLED':'1'}), \
             mock.patch.object(ark_media,'configured',return_value=True), \
             mock.patch.object(private_storage,'object_backend_configured',return_value=True):
            self.assertEqual(settings.readiness(),(True,''))
            db.execute('UPDATE public_trial_budget SET enabled=0 WHERE id=?',(settings.BUDGET_ID,))
            self.assertFalse(settings.readiness()[0])
            db.execute('UPDATE public_trial_budget SET enabled=1,reserved_milli_cny=100000 WHERE id=?',(settings.BUDGET_ID,))
            self.assertIn('预算',settings.readiness()[1])
            # A malformed persisted account assertion is rejected by read/validate.
            row=db.fetchone('SELECT value_json FROM system_settings WHERE key=?',('noteai_cover_config_v1',))
            state=json.loads(row['value_json']);state['active']['account_verified']=False
            db.execute('UPDATE system_settings SET value_json=? WHERE key=?',(json.dumps(state),'noteai_cover_config_v1'))
            self.assertFalse(settings.readiness()[0])

    def test_formal_readiness_uses_its_owner_metered_row_and_not_acceptance_cap(self):
        self.activate(execution_scope='formal')
        db.execute('UPDATE public_trial_budget SET reserved_milli_cny=100000,enabled=0 WHERE id=?',(settings.BUDGET_ID,))
        with mock.patch.dict(os.environ,{'NOTEAI_COVER_WORKER_ENABLED':'1'}), \
             mock.patch.object(ark_media,'configured',return_value=True), \
             mock.patch.object(private_storage,'object_backend_configured',return_value=True):
            self.assertEqual(settings.readiness(),(True,''))
            db.execute('UPDATE public_trial_budget SET enabled=0 WHERE id=?',(settings.FORMAL_BUDGET_ID,))
            self.assertFalse(settings.readiness()[0])

    def cost_fixture(self):
        user='settings-cost-owner';stamp=datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)',
            (user,user,user+'@example.invalid','fixture','fixture',stamp))
        billing.get_subscription(user);billing.grant_credits(user,64,'offline settings cost fixture')
        report=str(uuid.uuid4())
        db.execute('INSERT INTO saved_diagnoses(id,user_id,note_title,diagnosis_json,created_at) VALUES(?,?,?,?,?)',
            (report,user,'真实门店','{}',stamp))
        buffer=io.BytesIO();Image.new('RGB',(32,24),'blue').save(buffer,'PNG')
        source=private_storage.store_media_bytes(user,purpose='image',content_type='image/png',payload=buffer.getvalue(),item_count=1)
        policy=settings.policy_snapshot(self.config())
        def add(status,actual=None):
            task=cover_jobs.submit_job(user_id=user,report_type='analyze',report_id=report,request_id=str(uuid.uuid4()),
                source_refs=[source.id],input_snapshot={'note_title':'真实门店'},policy_snapshot=policy,
                quote_version=cover_jobs.policy_quote_version(policy))
            claim=cover_jobs.claim_job(task['job_id']);call=str(uuid.uuid4())
            db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)',
                (call,settings.BUDGET_ID,user,'fixture','dispatched',600,stamp,claim['charge']['usage_id']))
            cover_jobs.begin_image_call(claim,call_id=call,provider='seedream',model_id=settings.MODEL_ID,input_images=1,
                width=1776,height=2368,pricing_snapshot=policy['image_pricing'],estimated_cost='0.60',currency='CNY',price_version='fixture-price-v1')
            cover_jobs.finish_image_call(claim,call,status=status,output_images=1 if status=='responded' else 0,
                billed_images=1 if status=='responded' else None,actual_cost=actual,
                evidence_ref='fixture-original-bill' if actual is not None else None,http_status=200 if status=='responded' else None)
            return claim,call
        return user,add

    def test_cost_view_distinguishes_estimates_known_bills_and_unknown_outcomes(self):
        user,add=self.cost_fixture()
        unknown,call=add('unknown')
        add('responded',actual='0.59')
        summary=settings.cost_view()
        self.assertEqual(summary['status'],'readable')
        image=summary['images'][0]
        self.assertEqual((image['image_calls'],image['quantity_unknown_calls'],image['bill_unknown_calls'],image['outcome_unknown_calls']),(2,1,1,1))
        self.assertAlmostEqual(image['estimated_cost'],1.2)
        self.assertAlmostEqual(image['known_billed_cost'],0.59)
        self.assertIsNone(image['actual_total_cost'])
        self.assertNotIn(user,json.dumps(summary))
        self.assertNotIn('真实门店',json.dumps(summary,ensure_ascii=False))
        cover_jobs.reconcile_image_cost(user,unknown['request_id'],call,actual_cost='0.60',evidence_ref='fixture-original-unknown-bill',billed_images=1)
        reconciled=settings.cost_view()['images'][0]
        self.assertEqual(reconciled['outcome_unknown_calls'],1)
        self.assertAlmostEqual(reconciled['actual_total_cost'],1.19)

    def test_unreadable_cost_view_is_unknown_instead_of_a_zero_total(self):
        with mock.patch.object(db,'transaction',side_effect=RuntimeError('fixture table permission unavailable')):
            result=settings.cost_view()
        self.assertEqual(result['status'],'unavailable')
        self.assertIsNone(result['jobs']);self.assertIsNone(result['images'])

    def test_change_refuses_a_reserved_secret_setting_instead_of_false_success(self):
        db.execute('INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,1,?)',
            ('noteai_cover_config_v1_test','fixture-secret-not-a-real-credential',datetime.now(timezone.utc).isoformat()))
        self.assertFalse(settings.read('test')['active']['enabled'])
        with self.assertRaises(HTTPException) as denied:
            self.change('draft',config=self.config())
        self.assertEqual(denied.exception.status_code,409)
        self.assertEqual(db.fetchone('SELECT is_secret FROM system_settings WHERE key=?',('noteai_cover_config_v1_test',))[0],1)


if __name__=='__main__':unittest.main()
