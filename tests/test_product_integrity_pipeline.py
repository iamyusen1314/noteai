"""Synthetic pipeline handoffs; all model functions are replaced, no providers."""
import asyncio
import json
from unittest import TestCase, mock
from uuid import uuid4

from tests import test_product_integrity_api as fixture

api, db = fixture.api, fixture.db


class ProductIntegrityPipelineTests(TestCase):
    setUp = fixture.ProductIntegrityApiTests.setUp
    headers = fixture.ProductIntegrityApiTests.headers
    note = fixture.ProductIntegrityApiTests.note

    def session(self):
        note_id = self.note()
        sid = str(uuid4())
        session = dict(user_id=self.owner, note_id=note_id, note_title='原标题',
                       note_body='原正文', domain='美食', current_score=73,
                       messages=[], user_prefs={'emoji': 'STALE_PREFERENCE'},
                       generate_context={}, iteration_count=0, note_version=1)
        api._chat_sessions[sid] = session
        self.addCleanup(api._chat_sessions.pop, sid, None)
        return sid, session

    def prompt_dependencies(self):
        for name, value in (('_runtime_prompt', '本轮优化'), ('_get_dk', {}),
                            ('_get_quality_contract', ''), ('_get_feature_governance_brief', ''),
                            ('_build_generation_planning_brief', '')):
            self.stack.enter_context(mock.patch.object(api, name, return_value=value))

    def chat_dependencies(self):
        self.prompt_dependencies()
        self.calls = []
        async def stream(**kwargs):
            self.calls.append(kwargs)
            yield '离线已完成回复'
        self.stack.enter_context(mock.patch.object(api._mr, 'stream_chat', side_effect=stream))
        async def public_chunks(source):
            async for chunk in source:
                yield chunk
        self.stack.enter_context(mock.patch.object(api, '_public_model_content_chunks', side_effect=public_chunks))
        self.stack.enter_context(mock.patch.object(api, '_build_chat_plan_options', new=mock.AsyncMock(return_value=[])))
        self.stack.enter_context(mock.patch.object(api, '_extract_note_from_response', return_value=None))
        self.stack.enter_context(mock.patch.object(api, '_persist_chat_session', return_value=True))

    def collect(self, sid, message):
        async def consume():
            return [json.loads(line[6:]) async for line in api._chat_sse_generator(sid, message)
                    if line.startswith('data: ')]
        return asyncio.run(consume())

    def test_video_only_context_enters_first_chat_prompt_not_only_repair(self):
        self.prompt_dependencies()
        context = {'video_analysis': '原视频音画观察：SYNTHETIC_VIDEO_CONTEXT'}
        session = {'domain': '美食', 'generate_context': api._sanitize_chat_generate_context(context)}
        self.assertIn('SYNTHETIC_VIDEO_CONTEXT', api._chat_fact_source_for_turn(session, {}))
        self.assertIn('SYNTHETIC_VIDEO_CONTEXT', api._build_chat_system_prompt(session))

    def test_actual_predict_success_and_failure_record_only_the_executed_local_step(self):
        sentinel = object()
        with mock.patch.object(api, '_predict_impl', return_value=sentinel) as compute, \
             mock.patch.object(api._billing, 'record_local_step') as record:
            self.assertIs(api._predict('note'), sentinel)
            compute.assert_called_once_with('note', None, None, None)
            record.assert_called_once_with('local_score', 'succeeded')
        with mock.patch.object(api, '_predict_impl', side_effect=ValueError('synthetic')), \
             mock.patch.object(api._billing, 'record_local_step') as record:
            with self.assertRaises(ValueError):
                api._predict('note')
            record.assert_called_once_with('local_score', 'failed')

    def claim(self):
        return api._idempotency.claim_and_charge(user_id=self.owner, operation='generate',
                    request_id='offline-' + str(uuid4()), payload={'synthetic': True})

    def test_generation_canonical_save_and_growth_share_the_actual_transaction(self):
        claim = self.claim()
        result = {'note_title': '保存结果', 'note_body': '原始完整结果', 'ces_percentile': 85, 'grade': '优秀'}
        api._clarification.save_result(claim, result, new_generation={'domain': '美食'},
                                       record_growth=api._insert_growth_record_with_storage)
        note = db.fetchone('SELECT score FROM notes WHERE id=? AND user_id=?', (claim['request_id'], self.owner))
        growth = db.fetchall('SELECT note_id,score FROM growth_records WHERE user_id=?', (self.owner,))
        state = db.fetchone('SELECT status,complete_applied FROM idempotency_requests WHERE id=?', (claim['request_id'],))
        self.assertEqual(note['score'], 85)
        self.assertEqual([(r['note_id'], r['score']) for r in growth], [(claim['request_id'], 85)])
        self.assertEqual((state['status'], state['complete_applied']), ('completed', 1))

    def test_growth_callback_failure_rolls_back_canonical_note_and_completion(self):
        claim = self.claim()
        def failing(storage, **kwargs):
            api._insert_growth_record_with_storage(storage, **kwargs)
            raise RuntimeError('synthetic after growth insert')
        with self.assertRaises(RuntimeError):
            api._clarification.save_result(claim, {'note_title': '保存结果', 'note_body': '原始完整结果',
                'ces_percentile': 85, 'grade': '优秀'}, new_generation={'domain': '美食'}, record_growth=failing)
        for table in ('notes', 'growth_records', 'user_memories', 'chat_sessions'):
            self.assertEqual(db.fetchone(f'SELECT COUNT(*) AS n FROM {table} WHERE user_id=?', (self.owner,))['n'], 0)
        state = db.fetchone('SELECT status,complete_applied FROM idempotency_requests WHERE id=?', (claim['request_id'],))
        self.assertEqual((state['status'], state['complete_applied']), ('running', 0))

    def test_each_real_turn_refreshes_preferences_and_preserves_current_instruction(self):
        self.chat_dependencies()
        sid, session = self.session()
        with mock.patch.object(api._memory, 'read_preferences', side_effect=[{'emoji': 'FIRST'}, {'emoji': 'SECOND'}]) as read, \
             mock.patch.object(api._memory, 'build_memory_prompt', return_value=''), \
             mock.patch.object(api._memory, 'extract_explicit_preferences', return_value=[]):
            self.collect(sid, '本次不用表情')
            self.collect(sid, '仅本次用一个表情')
        self.assertEqual(read.call_args_list, [mock.call(self.owner, domain='美食')] * 2)
        self.assertIn('FIRST', self.calls[0]['system'])
        self.assertIn('SECOND', self.calls[1]['system'])
        self.assertNotIn('STALE_PREFERENCE', self.calls[0]['system'])
        self.assertEqual(self.calls[0]['user_content'], '本次不用表情')
        self.assertEqual(self.calls[1]['user_content'], '仅本次用一个表情')

    def test_preference_write_failure_does_not_hide_saved_note_or_claim_learning(self):
        self.chat_dependencies()
        sid, session = self.session()
        for name, result in (('_shape_body_for_delivery', '新的完整正文'),
                             ('_repair_chat_note_if_needed', ('新标题', '新的完整正文', 85, {}, '优秀', [], False))):
            self.stack.enter_context(mock.patch.object(api, name, new=mock.AsyncMock(return_value=result)))
        self.stack.enter_context(mock.patch.object(api, '_extract_note_from_response', return_value=('新标题', '新的完整正文')))
        self.stack.enter_context(mock.patch.object(api, '_sanitize_title_for_delivery', side_effect=lambda title, *args: title))
        self.stack.enter_context(mock.patch.object(api, '_has_blocking_quality_issues', return_value=False))
        self.stack.enter_context(mock.patch.object(api._memory, 'save_explicit_preferences', side_effect=RuntimeError('PRIVATE_SENTINEL')))
        events = self.collect(sid, '以后少用表情')
        self.assertTrue(db.fetchone('SELECT id FROM notes WHERE id=? AND user_id=?', (session['note_id'], self.owner)))
        self.assertNotEqual(session['note_version'], 1)
        self.assertIn('note_update', [e['type'] for e in events])
        self.assertIn('done', [e['type'] for e in events])
        learning = [e for e in events if e['type'] == 'learning']
        self.assertEqual([e.get('status') for e in learning], ['failed'])
        self.assertTrue(all('prefs' not in e for e in learning))
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(events))

    def test_new_public_write_verbs_cannot_bypass_origin_check(self):
        for method, path in (('PUT', '/auth/profile'), ('PATCH', '/auth/profile'),
                             ('DELETE', '/notes/' + str(uuid4())),
                             ('PATCH', '/profile/memories/' + str(uuid4())),
                             ('DELETE', '/profile/memories/' + str(uuid4()))):
            for origin in (None, 'https://attacker.invalid'):
                headers = self.headers()
                if origin is None:
                    headers.pop('Origin')
                else:
                    headers['Origin'] = origin
                with self.subTest(method=method, path=path, origin=origin):
                    response = self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(response.status_code, 403)
