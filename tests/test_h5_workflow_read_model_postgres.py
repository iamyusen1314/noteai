"""Opt-in SELECT/ACL compatibility in a new disposable local PG16 database."""
import asyncio
import importlib
import json
import os
import unittest
from uuid import uuid4

from tests import test_video_credit_consistency_postgres as pg_fixture


@unittest.skipUnless(os.environ.get('NOTEAI_LOCAL_PG16_CANARY_TEST') == '1',
                     'explicit isolated PG16 Unix socket required')
class H5WorkflowPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg_fixture.VideoCreditsPostgresTests.setUpClass.__func__(cls)
        cls.api = importlib.import_module('api')

    @classmethod
    def tearDownClass(cls):
        pg_fixture.VideoCreditsPostgresTests.tearDownClass.__func__(cls)

    connect = pg_fixture.VideoCreditsPostgresTests.connect
    setUp = pg_fixture.VideoCreditsPostgresTests.setUp
    tearDown = pg_fixture.VideoCreditsPostgresTests.tearDown

    def test_task_report_growth_note_and_conversation_projections_as_existing_api_role(self):
        user={'id':self.uid}
        claim=self.idempotency.claim_and_charge(user_id=self.uid,operation='analyze',
            request_id='pg-workflow-original',payload={'synthetic':True})
        note_id,report_id,session_id = str(uuid4()),str(uuid4()),str(uuid4())
        stamp=self.billing._now()
        self.api._insert_content_with_retention(
            'INSERT INTO notes(id,user_id,title,body,domain,source,version,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (note_id,self.uid,'PG synthetic','PG body','美食','analyze',1,stamp),'note',note_id,self.uid,created_at=stamp)
        receipt=self.billing.get_charge_receipt(self.uid,'analyze',claim['charge'])
        report={'saved_note_id':note_id,'billing':receipt,'ai_diagnosis':'PG synthetic','suggested_titles':[]}
        self.api._insert_content_with_retention(
            'INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)',
            (report_id,self.uid,'PG synthetic','美食',json.dumps(report),stamp),'diagnosis',report_id,self.uid,created_at=stamp)
        self.db.execute('INSERT INTO chat_sessions(id,user_id,note_id,domain,messages_json,generate_ctx_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                        (session_id,self.uid,note_id,'美食','[]','{}',stamp,stamp))
        self.api._insert_growth_record(user_id=self.uid,note_id=note_id,domain='美食',score=70,grade='良好',action='analyze')
        self.idempotency.mark_completed(claim)
        state=asyncio.run(self.api.read_chat_task(claim['request_id'],user))
        self.assertEqual(state['report_ref']['report_id'],report_id)
        self.assertEqual(state['billing']['credits_used'],6)
        listing=asyncio.run(self.api.pending_chat_tasks(user=user,view='activity',limit=1))
        self.assertEqual(listing['tasks'][0]['task_id'],claim['request_id'])
        chats=asyncio.run(self.api.pending_chat_tasks(user=user,view='conversations',note_id=note_id))
        self.assertEqual(chats['conversations'][0]['session_id'],session_id)
        self.assertEqual(asyncio.run(self.api.read_chat_task(session_id,user))['note_id'],note_id)
        self.assertEqual(asyncio.run(self.api.profile_growth(user))['records'][0]['report_ref']['report_id'],report_id)
        self.assertEqual(asyncio.run(self.api.list_notes(20,0,True,user))['groups'][0]['latest']['chat_session_id'],session_id)
        self.assertEqual(asyncio.run(self.api.list_reports(20,0,user))['reports'][0]['task_id'],claim['request_id'])
        self.assertEqual(self.db.fetchone('SELECT COUNT(*) n FROM usage_records WHERE user_id=?',(self.uid,))['n'],1)


if __name__ == '__main__':
    unittest.main()
