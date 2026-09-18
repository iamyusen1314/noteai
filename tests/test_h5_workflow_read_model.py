"""H5 reads use original paid claims/reports/chats; isolated synthetic data only."""
import asyncio
from datetime import timedelta
import json
import os
from types import SimpleNamespace
import unittest
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests import test_report_history as report_history
api, db, product = report_history.api, report_history.db, report_history.product
import billing
import idempotency


class H5WorkflowReadModelTests(unittest.TestCase):
    setUp = report_history.ReportHistoryTests.setUp
    tearDown = report_history.ReportHistoryTests.tearDown
    insert_note = report_history.ReportHistoryTests.insert_note
    generation = report_history.ReportHistoryTests.generation

    def claim(self, key='workflow-original', operation='analyze'):
        return idempotency.claim_and_charge(user_id=self.user['id'], operation=operation,
            request_id=key, payload={'synthetic': True})

    def diagnosis(self):
        claim = self.claim()
        note_id, report_id = str(uuid4()), str(uuid4())
        self.insert_note(self.user, note_id, '诊断原文', '原正文', 'analyze')
        # Actual analyze persistence writes a receipt with usage_id but request_id=None.
        receipt = billing.get_charge_receipt(self.user['id'], 'analyze', claim['charge'])
        result = {'saved_note_id': note_id, 'billing': receipt, 'ai_diagnosis': '原诊断',
                  'ces_percentile': 67.0, 'composite_score': 67.0, 'grade': '良好', 'suggested_titles': []}
        stamp = self.now.isoformat()
        api._insert_content_with_retention(
            'INSERT INTO saved_diagnoses(id,user_id,note_title,domain,ces_percentile,composite_score,grade,diagnosis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (report_id,self.user['id'],'诊断原文','美食',67,67,'良好',json.dumps(result),stamp),
            'diagnosis',report_id,self.user['id'],created_at=stamp)
        idempotency.mark_completed(claim)
        api._insert_growth_record(user_id=self.user['id'], note_id=note_id, domain='美食',
                                 score=67, grade='良好', action='analyze')
        return claim, note_id, report_id

    def conversation(self, note_id, *, user=None, messages=None):
        owner = user or self.user
        sid = str(uuid4()); stamp = self.now.isoformat()
        db.execute('INSERT INTO chat_sessions(id,user_id,note_id,domain,generate_ctx_json,messages_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (sid,owner['id'],note_id,'美食','{}',json.dumps(messages or []),stamp,stamp))
        return sid

    def tasks(self, **kwargs):
        return asyncio.run(api.pending_chat_tasks(user=self.user, **kwargs))

    def read(self, task_id, user=None):
        return asyncio.run(api.read_chat_task(task_id, user or self.user))

    def test_running_task_is_readable_by_id_and_original_client_key_without_writes(self):
        claim = self.claim()
        transaction = db.transaction
        def readonly(*, write=False):
            self.assertFalse(write)
            return transaction(write=False)
        with mock.patch.object(db, 'execute', side_effect=AssertionError('read wrote DB')), \
             mock.patch.object(db, 'transaction', side_effect=readonly), \
             mock.patch.object(idempotency, 'claim_and_charge', side_effect=AssertionError('read admitted work')), \
             mock.patch.object(api._mr, 'call', side_effect=AssertionError('read called model')):
            current = self.read(claim['request_id'])
            recovered = self.tasks(request_id='workflow-original', operation='analyze')['tasks'][0]
            listing = self.tasks(view='activity')
        self.assertEqual(recovered, current)
        self.assertEqual(current['status'], 'running')
        self.assertEqual(current['billing']['credits_used'], 6)
        self.assertIsNone(current['report_ref'])
        self.assertIsNone(current['note_title'])
        self.assertFalse(current['can_cancel']); self.assertFalse(current['can_retry'])
        self.assertFalse(current['durable_execution'])
        self.assertIn(claim['request_id'], [task['task_id'] for task in listing['tasks']])
        self.assertEqual(db.fetchone('SELECT COUNT(*) n FROM usage_records')['n'], 1)
        for private in ('lease_token', 'key_hash', 'payload_hash', 'prepared', 'request_hash'):
            self.assertNotIn(private, json.dumps(current))

    def test_expired_and_physical_unknown_stay_unknown_and_do_not_allow_retry(self):
        claim = self.claim()
        db.execute('UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?',
                   ((self.now-timedelta(minutes=1)).isoformat(), claim['request_id']))
        state = self.read(claim['request_id'])
        self.assertEqual((state['status'], state['recorded_status']), ('outcome_unknown', 'running'))
        self.assertFalse(state['can_retry'])
        db.execute('UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?',
                   ((self.now+timedelta(hours=1)).isoformat(), claim['request_id']))
        db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)',
                   (str(uuid4()), 'website-free-product-20260912', self.user['id'], 'synthetic', 'unknown', 1, self.now.isoformat(), claim['charge']['usage_id']))
        state = self.read(claim['request_id'])
        self.assertEqual(state['status'], 'outcome_unknown')
        self.assertEqual(state['billing']['status'], 'charged')
        self.assertFalse(state['can_retry'])
        self.assertEqual(db.fetchone('SELECT status,refund_applied FROM idempotency_requests WHERE id=?',
                                    (claim['request_id'],))['refund_applied'], 0)

    def test_confirmed_failed_task_shows_original_refund_and_retry_eligibility(self):
        claim = self.claim()
        idempotency.mark_failed_and_refund(claim)
        state = self.read(claim['request_id'])
        self.assertEqual(state['status'], 'failed'); self.assertTrue(state['can_retry'])
        self.assertEqual((state['billing']['credits_used'],state['billing']['refunded_credits']), (0,6))
        self.assertEqual(self.tasks(request_id='workflow-original', operation='analyze')['tasks'][0], state)

    def test_completed_diagnosis_links_exact_note_report_growth_task_and_chat(self):
        claim, note_id, report_id = self.diagnosis()
        session = self.conversation(note_id)
        state = self.read(claim['request_id'])
        ref = {'report_type':'analyze','report_id':report_id,'task_id':claim['request_id']}
        self.assertEqual(state['report_ref'], ref); self.assertEqual(state['note_id'],note_id)
        reports = asyncio.run(api.list_reports(20,0,self.user))['reports']
        report = next(item for item in reports if item['report_id'] == report_id)
        self.assertEqual((report['saved_note_id'],report['task_id'],report['chat_session_id']), (note_id,claim['request_id'],session))
        detail = asyncio.run(api.get_report('analyze',report_id,self.user))
        self.assertEqual(detail['task_id'],claim['request_id']); self.assertEqual(detail['chat_session_id'],session)
        flat = asyncio.run(api.list_notes(20,0,False,self.user))['notes']
        note = next(item for item in flat if item['id']==note_id)
        self.assertEqual(note['report_ref'],ref); self.assertEqual(note['chat_session_id'],session)
        grouped=asyncio.run(api.list_notes(20,0,True,self.user))['groups']
        self.assertEqual(next(group for group in grouped if group['group_id']==note_id)['latest']['report_ref'],ref)
        versions=asyncio.run(api.note_versions(note_id,self.user))['versions']
        self.assertEqual(versions[0]['report_ref'],ref)
        growth=asyncio.run(api.profile_growth(self.user))['records'][0]
        self.assertTrue(growth['id']); self.assertEqual(growth['note_id'],note_id); self.assertEqual(growth['report_ref'],ref)

    def test_generation_task_and_report_recover_original_not_rewrite(self):
        child=str(uuid4()); self.insert_note(self.user,child,'改写','改写正文','chat',self.report_id,2)
        state=self.read(self.report_id)
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['note_id'],self.report_id)
        self.assertEqual(state['report_ref']['report_id'],self.report_id)
        self.assertEqual(asyncio.run(api.get_report('generate',self.report_id,self.user))['result']['note_body'],'原生成正文')
        self.assertIsNone(next(note for note in asyncio.run(api.list_notes(20,0,False,self.user))['notes'] if note['id']==child)['report_ref'])

    def test_conversations_are_exact_version_and_exclude_clarification_sessions(self):
        child=str(uuid4()); self.insert_note(self.user,child,'改写','改写正文','chat',self.report_id,2)
        original_session=self.conversation(self.report_id)
        child_session=self.conversation(child)
        data=self.tasks(view='conversations',note_id=self.report_id)
        self.assertEqual([chat['session_id'] for chat in data['conversations']],[original_session])
        self.assertEqual(data['conversations'][0]['note_version'],1)
        self.assertEqual([chat['session_id'] for chat in self.tasks(view='conversations',note_id=child)['conversations']],[child_session])
        self.assertNotIn(self.report_id,[chat['session_id'] for chat in self.tasks(view='conversations')['conversations']])
        self.assertEqual(self.tasks(), {'tasks':[]})

    def test_chat_read_restores_only_public_messages_with_exact_note_context(self):
        sid=self.conversation(self.report_id,messages=[{'role':'user','content':'原问题'},
            {'role':'assistant','content':'原回复'},{'role':'system','content':'PRIVATE-SYSTEM'},
            {'role':'assistant','content':'PRIVATE-RAW','raw':'private'}])
        state=self.read(sid)
        self.assertEqual(state['type'],'chat_state'); self.assertEqual(state['note_id'],self.report_id)
        self.assertEqual(state['messages'],[{'role':'user','content':'原问题'},{'role':'assistant','content':'原回复'}])
        self.assertEqual(state['report_ref']['report_id'],self.report_id)
        self.assertNotIn('PRIVATE-',json.dumps(state))
        self.assertEqual(db.fetchone('SELECT COUNT(*) n FROM chat_sessions')['n'],2)

    def test_foreign_missing_deleted_and_malformed_links_fail_closed(self):
        claim,note_id,report_id=self.diagnosis(); sid=self.conversation(note_id)
        for identity in (claim['request_id'],sid,self.report_id,str(uuid4())):
            with self.assertRaises(HTTPException) as denied:self.read(identity,self.other)
            self.assertEqual(denied.exception.status_code,404)
        with self.assertRaises(HTTPException):
            asyncio.run(api.pending_chat_tasks(user=self.other,request_id='workflow-original',operation='analyze'))
        db.execute('UPDATE content_retention SET deleted_at=? WHERE content_type=? AND content_id=?',
                   (self.now.isoformat(),'note',note_id))
        with self.assertRaises(HTTPException):self.read(sid)
        self.assertFalse(self.tasks(view='conversations')['conversations'])
        growth=asyncio.run(api.profile_growth(self.user))['records'][0]
        self.assertIsNone(growth['note_id']); self.assertIsNone(growth['report_ref'])
        self.assertIsNone(next(item for item in asyncio.run(api.list_reports(20,0,self.user))['reports'] if item['report_id']==report_id)['saved_note_id'])
        db.execute('UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?', ('not-json',report_id))
        self.assertIsNone(next(item for item in asyncio.run(api.list_reports(20,0,self.user))['reports'] if item['report_id']==report_id)['task_id'])

    def test_legacy_receiptless_diagnosis_uses_exact_continuation_ids_only(self):
        claim,note_id,report_id=self.diagnosis()
        row=db.fetchone('SELECT diagnosis_json FROM saved_diagnoses WHERE id=?',(report_id,))
        result=json.loads(row['diagnosis_json']); result.pop('billing'); result['diagnosis_id']=report_id
        db.execute('UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?',(json.dumps(result),report_id))
        task={'operation':'analyze','status':'completed','version':1,'questions':[],'result':result}
        db.execute('INSERT INTO chat_sessions(id,user_id,note_id,domain,generate_ctx_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                   (claim['request_id'],self.user['id'],note_id,'美食',json.dumps({'task_continuation':task}),self.now.isoformat(),self.now.isoformat()))
        self.assertEqual(self.read(claim['request_id'])['report_ref']['report_id'],report_id)
        task['result']['diagnosis_id']=str(uuid4())
        db.execute('UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?',
                   (json.dumps({'task_continuation':task}),claim['request_id']))
        self.assertIsNone(self.read(claim['request_id'])['report_ref'])

    def test_active_dispatched_call_is_not_mislabelled_as_unknown(self):
        claim=self.claim()
        db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)',
                   (str(uuid4()),'website-free-product-20260912',self.user['id'],'synthetic','dispatched',1,self.now.isoformat(),claim['charge']['usage_id']))
        self.assertEqual(self.read(claim['request_id'])['status'],'running')

    def test_activity_pagination_and_views_are_bounded_and_owner_scoped(self):
        claim=self.claim(); self.generation(self.other)
        data=self.tasks(view='activity',limit=1)
        self.assertEqual(data['total'],2); self.assertEqual(len(data['tasks']),1)
        self.assertNotEqual(data['tasks'][0]['task_id'],self.tasks(view='activity',limit=1,offset=1)['tasks'][0]['task_id'])
        for kwargs in ({'limit':0},{'limit':101},{'offset':-1},{'view':'raw'},
                       {'request_id':'workflow-original','operation':'chat_rewrite'},
                       {'view':'conversations','note_id':str(uuid4())}):
            with self.assertRaises(HTTPException):self.tasks(**kwargs)

    def test_public_http_gets_auth_and_original_routes_remain_closed_for_mutations(self):
        claim=self.claim(); sid=self.conversation(self.report_id)
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_ACCOUNT_ONLY':'1','NOTEAI_PUBLIC_PRODUCT':'1'}), \
             mock.patch.object(product,'authenticated_user',new=mock.AsyncMock(return_value=self.user)):
            api.app.dependency_overrides[api._auth.get_current_user]=lambda:self.user
            try:
                client=TestClient(api.app)
                for path in ('/chat/tasks?view=activity','/chat/tasks?view=conversations',
                             '/chat/tasks/'+claim['request_id'],'/chat/tasks/'+sid):
                    response=client.get(path)
                    self.assertEqual(response.status_code,200,(path,response.text))
                    self.assertEqual(response.headers['cache-control'],'no-store')
                response=client.get('/chat/tasks?operation=analyze',headers={'X-Request-ID':'workflow-original'})
                self.assertEqual(response.json()['tasks'][0]['task_id'],claim['request_id'])
                self.assertEqual(client.get('/chat/tasks/'+str(uuid4())).status_code,404)
                self.assertEqual(client.delete('/chat/tasks/'+claim['request_id']).status_code,404)
                self.assertEqual(client.post('/chat/tasks/'+claim['request_id']+'/cancel').status_code,404)
                self.assertEqual(client.get('/ai/jobs/'+claim['request_id']).status_code,404)
            finally:api.app.dependency_overrides.pop(api._auth.get_current_user,None)
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_ACCOUNT_ONLY':'1','NOTEAI_PUBLIC_PRODUCT':'1'}), \
             mock.patch.object(product,'authenticated_user',new=mock.AsyncMock(side_effect=HTTPException(401,'login required'))):
            self.assertEqual(TestClient(api.app).get('/chat/tasks?view=activity').status_code,401)

    def test_sse_task_created_precedes_pipeline_and_matches_get_and_receipt(self):
        async def pipeline(*args,emit=None,**kwargs):
            if emit: await emit({'type':'stage','stage':'analysis'})
            return SimpleNamespace(model_dump=lambda:{'type':'complete','diagnosis_id':'synthetic'})
        with mock.patch.object(api,'_run_analyze_pipeline',new=mock.AsyncMock(side_effect=pipeline)) as run:
            async def consume():
                response=await api.analyze_stream_endpoint(api.AnalyzeInput(note_title='synthetic',desc='body'),
                    self.user,request_id='sse-workflow-key',quote_version=billing.billing_quote_version())
                stream=response.body_iterator
                first=json.loads((await anext(stream)).removeprefix('data: ').strip())
                self.assertEqual(run.await_count,0)
                remaining=[json.loads(chunk.removeprefix('data: ').strip()) async for chunk in stream]
                return first,remaining
            first,remaining=asyncio.run(consume())
        self.assertEqual(first['type'],'task_created')
        self.assertEqual(first['billing']['request_id'],first['task_id'])
        self.assertEqual(first['billing']['credits_used'],6)
        self.assertNotEqual(first['trace_id'],first['task_id'])
        self.assertEqual(remaining[-1]['type'],'complete')
        self.assertEqual(self.read(first['task_id'])['status'],'completed')
        self.assertEqual(db.fetchone('SELECT COUNT(*) n FROM usage_records')['n'],1)

    def test_default_waiting_semantics_and_resume_contract_are_preserved(self):
        claim=self.claim(); stamp=self.now.isoformat()
        task={'operation':'analyze','status':'waiting_for_input','version':2,'questions':[],
              'answers':[],'completed_steps':['media'],'prepared':{'internal_prompt':'PRIVATE'}}
        db.execute('INSERT INTO chat_sessions(id,user_id,domain,generate_ctx_json,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                   (claim['request_id'],self.user['id'],'美食',json.dumps({'task_continuation':task}),stamp,stamp))
        db.execute("UPDATE idempotency_requests SET status='waiting_for_input' WHERE id=?",(claim['request_id'],))
        self.assertEqual(self.tasks()['tasks'][0]['session_id'],claim['request_id'])
        state=self.read(claim['request_id'])
        self.assertEqual(state['type'],'clarification_required'); self.assertEqual(state['version'],2)
        self.assertTrue(state['can_resume']); self.assertFalse(state['can_retry']); self.assertFalse(state['can_cancel'])
        self.assertNotIn('PRIVATE',json.dumps(state)); self.assertEqual(state['billing']['credits_used'],6)


if __name__ == '__main__':
    unittest.main()
