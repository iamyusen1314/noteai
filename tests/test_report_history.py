"""Original completed report recovery, using only isolated SQLite and mocked auth."""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
db = importlib.import_module('db')
api = importlib.import_module('api')
product = importlib.import_module('public_product')


class ReportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / 'reports.sqlite'
        db.init_db()
        self.user = {'id': str(uuid4())}
        self.other = {'id': str(uuid4())}
        self.now = datetime.now(timezone.utc)
        for user in (self.user, self.other):
            db.execute('INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)',
                       (user['id'], user['id'], user['id']+'@example.invalid', 'synthetic', 'synthetic', self.now.isoformat()))
        self.report_id, self.result = self.generation(self.user)

    def tearDown(self):
        db._DB_PATH = self.old_db
        self.temp.cleanup()

    def insert_note(self, user, note_id, title, body, source='generate', parent=None, version=1, created=None):
        stamp = created or self.now.isoformat()
        api._insert_content_with_retention(
            'INSERT INTO notes(id,user_id,title,body,domain,score,grade,source,parent_id,version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (note_id, user['id'], title, body, '美食', 73.2, '良好', source, parent, version, stamp),
            'note', note_id, user['id'], created_at=stamp)

    def generation(self, user, *, status='completed', operation='generate', saved_id=None):
        rid = str(uuid4()); stamp = self.now.isoformat()
        self.insert_note(user, rid, '原生成标题', '原生成正文')
        db.execute("INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,lease_expires_at,complete_applied,created_at,updated_at,completed_at,usage_id,usage_created,charge_applied) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'synthetic',1,1)",
                   (rid, user['id'], operation, rid, 'synthetic', status, 'synthetic', stamp, int(status=='completed'), stamp, stamp, stamp))
        role = next(iter(api._PUBLIC_EXPERT_ROLES))
        result = {'type':'complete', 'note_title':'原生成标题', 'note_body':'原生成正文',
                  'title_variants':['原候选'], 'ces_percentile':73.2, 'grade':'良好',
                  'saved_note_id':saved_id or rid, 'saved_note_version':1, 'cover_analysis':'原视频和封面观察',
                  'features':{}, 'feature_hits':{'has_address':True}, 'model_used':'synthetic-original-model',
                  'fact_context':'原已确认素材', 'original_fact_context':'原用户简报',
                  'fact_enrichment':{'enabled':True,'provider':'amap','query':'原门店',
                                     'facts':{'address':'原地址'},'sources':[{'title':'原来源','url':'https://example.invalid/source'}]},
                  'expert_opinions':[{'role':role, 'opinion':'原公开建议', 'reason':'原公开依据', 'raw':'RAW-MUST-NOT-ESCAPE'}],
                  'quality_issues':['原事实仍待确认'], 'pending_confirmation':['原未确认事项'],
                  'private_transport':'PRIVATE-TRANSPORT',
                  'selection_meta':{'candidate_count':2,'selected_title':'原生成标题','candidates':[]}}
        task = {'operation':operation, 'status':status, 'result':result, 'questions':[], 'answers':[],
                'prepared':{'pipeline':'generate_stream','internal_prompt':'PREPARED-MUST-NOT-ESCAPE'}}
        db.execute('INSERT INTO chat_sessions(id,user_id,note_id,domain,generate_ctx_json,messages_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (rid,user['id'],rid,'美食',json.dumps({'task_continuation':task},ensure_ascii=False),
                    json.dumps([{'role':'system','content':'MESSAGES-MUST-NOT-ESCAPE'}]),stamp,stamp))
        return rid,result

    def diagnosis(self):
        did = str(uuid4()); stamp = (self.now-timedelta(minutes=10)).isoformat()
        result = {'ai_diagnosis':'原诊断', 'ces_percentile':65.0, 'composite_score':65.0,
                  'suggested_titles':['原诊断方案'], 'suggested_body':'原建议正文', 'grade':'合格'}
        api._insert_content_with_retention(
            'INSERT INTO saved_diagnoses(id,user_id,note_title,domain,ces_percentile,composite_score,grade,diagnosis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (did,self.user['id'],'原诊断标题','美食',65.0,65.0,'合格',json.dumps(result,ensure_ascii=False),stamp),
            'diagnosis',did,self.user['id'],created_at=stamp)
        return did

    def detail(self, rid=None, user=None):
        return asyncio.run(api.get_report('generate',rid or self.report_id,user or self.user))

    def test_lists_completed_generation_and_diagnosis_with_stable_pagination(self):
        did=self.diagnosis();self.generation(self.other)
        data=asyncio.run(api.list_reports(1,0,self.user))
        self.assertEqual(data['total'],2);self.assertEqual(data['reports'][0]['report_id'],self.report_id)
        self.assertEqual(data['reports'][0]['report_type'],'generate')
        page=asyncio.run(api.list_reports(1,1,self.user))
        self.assertEqual(page['reports'][0]['report_id'],did);self.assertEqual(page['reports'][0]['report_type'],'analyze')
        self.assertNotIn('note_body',json.dumps(data))

    def test_full_original_public_generation_survives_rewrite_and_refresh(self):
        child=str(uuid4())
        self.insert_note(self.user,child,'后来的改写标题','后来的改写正文','chat',self.report_id,2,(self.now+timedelta(minutes=2)).isoformat())
        detail=self.detail();result=detail['result']
        self.assertEqual(result['note_title'],self.result['note_title']);self.assertEqual(result['note_body'],self.result['note_body'])
        for key in ('cover_analysis','fact_context','original_fact_context','fact_enrichment','model_used','quality_issues','pending_confirmation','title_variants','selection_meta','saved_note_id','saved_note_version','feature_hits','features'):
            self.assertEqual(result[key],self.result[key],key)
        self.assertEqual(result['expert_opinions'][0]['opinion'],'原公开建议')
        self.assertEqual(result['note_version_group']['latest']['id'],child)
        self.assertEqual(result['note_version_group']['version_count'],2)
        encoded=json.dumps(detail)
        for private in ('PRIVATE-TRANSPORT','PREPARED-MUST-NOT-ESCAPE','MESSAGES-MUST-NOT-ESCAPE','RAW-MUST-NOT-ESCAPE'):
            self.assertNotIn(private,encoded)

    def test_no_writes_provider_calls_or_billing_changes_on_read(self):
        before=db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(self.report_id,))['generate_ctx_json']
        transaction=db.transaction
        def read_transaction(*,write=False):
            self.assertFalse(write);return transaction(write=False)
        with mock.patch.object(db,'execute',side_effect=AssertionError('read wrote DB')), \
             mock.patch.object(db,'transaction',side_effect=read_transaction), \
             mock.patch.object(api._mr,'call',side_effect=AssertionError('read called model')):
            self.detail();asyncio.run(api.list_reports(20,0,self.user))
        self.assertEqual(db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(self.report_id,))['generate_ctx_json'],before)
        self.assertEqual(db.fetchone('SELECT COUNT(*) AS n FROM usage_records')['n'],0)

    def test_foreign_owner_cannot_read_or_list_original_report(self):
        with self.assertRaises(HTTPException)as denied:self.detail(user=self.other)
        self.assertEqual(denied.exception.status_code,404)
        self.assertEqual(asyncio.run(api.list_reports(20,0,self.other)),{'reports':[],'total':0})

    def test_waiting_failed_rewrite_and_incomplete_claim_are_excluded(self):
        self.generation(self.user,status='waiting_for_input');self.generation(self.user,status='failed')
        self.generation(self.user,operation='chat_rewrite')
        other,_=self.generation(self.user)
        db.execute('UPDATE idempotency_requests SET complete_applied=0 WHERE id=?',(other,))
        data=asyncio.run(api.list_reports(20,0,self.user))
        self.assertEqual([r['report_id']for r in data['reports']],[self.report_id])

    def test_mismatched_saved_note_link_never_reads_a_different_version(self):
        bad,_=self.generation(self.user,saved_id=self.report_id)
        with self.assertRaises(HTTPException)as denied:self.detail(bad)
        self.assertEqual(denied.exception.status_code,404)

    def test_deleted_and_expired_original_note_hide_report(self):
        db.execute('UPDATE content_retention SET deleted_at=? WHERE content_type=? AND content_id=?',
                   (self.now.isoformat(),'note',self.report_id))
        with self.assertRaises(HTTPException):self.detail()
        self.assertEqual(asyncio.run(api.list_reports(20,0,self.user))['total'],0)
        db.execute('UPDATE content_retention SET deleted_at=NULL,active_until=?,recovery_until=?,purge_after=? WHERE content_type=? AND content_id=?',
                   ((self.now-timedelta(days=1)).isoformat(),(self.now+timedelta(days=1)).isoformat(),(self.now+timedelta(days=1)).isoformat(),'note',self.report_id))
        with self.assertRaises(HTTPException):self.detail()

    def test_missing_original_note_does_not_manufacture_a_report(self):
        db.execute('UPDATE chat_sessions SET note_id=NULL WHERE id=?',(self.report_id,))
        db.execute('DELETE FROM notes WHERE id=?',(self.report_id,))
        with self.assertRaises(HTTPException):self.detail()

    def test_legacy_diagnosis_detail_and_endpoint_are_unchanged(self):
        did=self.diagnosis()
        old=asyncio.run(api.get_diagnosis(did,self.user));new=asyncio.run(api.get_report('analyze',did,self.user))
        self.assertEqual(new['result'],old)
        self.assertEqual(asyncio.run(api.list_diagnoses(20,0,self.user))['total'],1)

    def test_missing_prepared_metadata_does_not_invent_expert_provenance(self):
        row=db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(self.report_id,))
        stored=json.loads(row['generate_ctx_json']);task=stored['task_continuation']
        task.pop('prepared');task['answers']=[{'question_id':'synthetic'}]
        db.execute('UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?',(json.dumps(stored),self.report_id))
        self.assertNotIn('expert_opinions_basis',self.detail()['result'])
        task['result']['expert_opinions_basis']='pre_clarification'
        db.execute('UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?',(json.dumps(stored),self.report_id))
        self.assertEqual(self.detail()['result']['expert_opinions_basis'],'pre_clarification')

    def test_malformed_stored_task_is_not_rebuilt_from_note(self):
        db.execute('UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?',('{invalid',self.report_id))
        self.assertEqual(asyncio.run(api.list_reports(20,0,self.user))['total'],0)
        with self.assertRaises(HTTPException):self.detail()

    def test_equal_timestamps_have_repeatable_page_order(self):
        second,_=self.generation(self.user)
        expected=sorted([self.report_id,second],reverse=True)
        self.assertEqual([asyncio.run(api.list_reports(1,i,self.user))['reports'][0]['report_id'] for i in (0,1)],expected)

    def test_bad_pagination_and_unknown_report_type_fail_closed(self):
        for limit,offset in ((0,0),(101,0),(10,-1)):
            with self.assertRaises(HTTPException):asyncio.run(api.list_reports(limit,offset,self.user))
        with self.assertRaises(HTTPException):asyncio.run(api.get_report('chat',self.report_id,self.user))

    def test_public_boundary_accepts_only_two_new_get_shapes(self):
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_ACCOUNT_ONLY':'1','NOTEAI_PUBLIC_PRODUCT':'1'}), \
             mock.patch.object(product,'authenticated_user',new=mock.AsyncMock(return_value=self.user)):
            api.app.dependency_overrides[api._auth.get_current_user]=lambda:self.user
            try:
                client=TestClient(api.app)
                self.assertEqual(client.get('/reports').status_code,200)
                reply=client.get('/reports/generate/'+self.report_id)
                self.assertEqual(reply.status_code,200,reply.text);self.assertEqual(reply.headers['cache-control'],'no-store')
                for method,path in [('POST','/reports'),('DELETE','/reports/generate/'+self.report_id),
                                    ('GET','/reports/chat/'+self.report_id),('GET','/reports/generate/not-an-id'),
                                    ('GET','/admin/reports')]:
                    self.assertEqual(client.request(method,path).status_code,404,(method,path))
            finally:api.app.dependency_overrides.pop(api._auth.get_current_user,None)

    def test_public_boundary_keeps_authentication(self):
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_ACCOUNT_ONLY':'1','NOTEAI_PUBLIC_PRODUCT':'1'}), \
             mock.patch.object(product,'authenticated_user',new=mock.AsyncMock(side_effect=HTTPException(401,'login required'))):
            client=TestClient(api.app)
            self.assertEqual(client.get('/reports').status_code,401)
            self.assertEqual(client.get('/reports/generate/'+self.report_id).status_code,401)

    def test_nginx_report_locations_match_the_two_public_read_shapes(self):
        text=(ROOT/'deploy/production/public-account.locations.conf').read_text()
        body='\n    limit_except GET { deny all; }\n    include /etc/nginx/noteai-product-proxy.conf;\n'
        self.assertIn('location = /reports {'+body+'}',text)
        pattern=re.search(r'location ~ "(\^/reports/[^"\n]+)" \{',text).group(1)
        self.assertIn('location ~ "'+pattern+'" {'+body+'}',text)
        for kind in ('analyze','generate'):
            for rid in (self.report_id,self.report_id.replace('-','')):
                self.assertIsNotNone(re.fullmatch(pattern,'/reports/'+kind+'/'+rid))
        for path in ('/reports/chat/'+self.report_id,'/reports/generate/not-an-id',
                     '/reports/generate/'+self.report_id+'/versions','/admin/reports'):
            self.assertIsNone(re.fullmatch(pattern,path))

if __name__=='__main__':unittest.main()
