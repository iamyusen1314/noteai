"""Actual public API routes with synthetic accounts and isolated SQLite only."""
import base64
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
with tempfile.TemporaryDirectory() as boot:
    with mock.patch.dict(os.environ, {'DATABASE_URL': '', 'NOTEAI_SQLITE_PATH': str(Path(boot) / 'boot.db'),
                                     'NOTEAI_HOT_KEYWORD_DB_PATH': str(Path(boot) / 'hot.db')}):
        import api
        import db
        import memory
        import usage_reporting


class ProductIntegrityApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(mock.patch.object(db, '_DB_PATH', Path(self.temp) / 'test.db'))
        self.stack.enter_context(mock.patch.object(db, 'using_postgres', return_value=False))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'DATABASE_URL': '', 'NOTEAI_PUBLIC_ACCOUNT_ONLY': '1', 'NOTEAI_PUBLIC_PRODUCT': '1',
            'NOTEAI_PUBLIC_MEDIA_ENABLED': '0', 'NOTEAI_PUBLIC_VIDEO_ENABLED': '0',
            'NOTEAI_PUBLIC_ORIGINS': 'https://noteai-test.example.invalid',
        }))
        self.stack.enter_context(mock.patch.object(api._mr, 'call', side_effect=AssertionError('provider prohibited')))
        db.init_db()
        self.now = datetime.now(timezone.utc)
        self.owner, self.other = str(uuid4()), str(uuid4())
        self.tokens = {}
        for uid in (self.owner, self.other):
            db.execute('INSERT INTO users(id,username,email,password_hash,password_salt,created_at,phone_verified_at) VALUES(?,?,?,?,?,?,?)',
                       (uid, uid, uid+'@example.invalid', 'offline', 'offline', self.now.isoformat(), self.now.isoformat()))
            token = 'offline-token-' + uid
            self.tokens[uid] = token
            db.execute('INSERT INTO user_sessions(token,user_id,created_at,expires_at,user_agent) VALUES(?,?,?,?,?)',
                       (token, uid, self.now.isoformat(), (self.now+timedelta(days=1)).isoformat(), 'isolated-test'))
            db.execute('INSERT INTO user_contract_acceptances VALUES(?,?,?,?,?)',
                       (uid, api._public_product.CONTRACT_VERSION, self.now.isoformat(), '', 'account_settings'))
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def headers(self, user=None):
        return {'Authorization': 'Bearer ' + self.tokens[user or self.owner],
                'Origin': 'https://noteai-test.example.invalid'}

    def get(self, path, user=None):
        return self.client.get(path, headers=self.headers(user))

    def note(self, user=None, *, score=73, source='manual', created=None):
        uid, nid = user or self.owner, str(uuid4())
        stamp = created or self.now.isoformat()
        api._insert_content_with_retention(
            'INSERT INTO notes(id,user_id,title,body,domain,score,grade,source,version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (nid, uid, '离线真实保存标题', '离线原素材正文', '美食', score, '良好', source, 1, stamp),
            'note', nid, uid, created_at=stamp)
        return nid

    def original_generation(self, user=None, *, score=73):
        uid = user or self.owner
        nid = self.note(uid, score=score, source='generate')
        rid = str(uuid4())
        stamp = self.now.isoformat()
        db.execute('INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,lease_expires_at,complete_applied,created_at,updated_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid, uid, 'generate', rid, 'offline', 'completed', 'offline', stamp, 1, stamp, stamp, stamp))
        result = {'saved_note_id': nid, 'ces_percentile': score, 'note_body': 'PRIVATE_SOURCE_NOT_A_GROWTH_FIELD'}
        context = {'task_continuation': {'operation': 'generate', 'status': 'completed', 'result': result}}
        db.execute('INSERT INTO chat_sessions(id,user_id,note_id,domain,generate_ctx_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                   (rid, uid, nid, '美食', json.dumps(context), stamp, stamp))
        return rid, nid

    def test_profile_put_and_patch_persist_reload_without_token_rotation(self):
        initial_tokens = [dict(x) for x in db.fetchall('SELECT * FROM user_sessions ORDER BY user_id')]
        image = BytesIO()
        Image.new('RGB', (2, 2), (12, 34, 56)).save(image, format='PNG')
        avatar = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        for method, payload in (('PUT', {'nickname': '测试昵称', 'avatar_emoji': '🌻'}),
                                ('PATCH', {'avatar_data': avatar})):
            response = self.client.request(method, '/auth/profile', headers=self.headers(), json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['ok'])
        owner = self.get('/auth/me').json()
        self.assertEqual(owner['nickname'], '测试昵称')
        self.assertTrue(owner['avatar_data'].startswith('data:image/png;base64,'))
        self.assertNotEqual(self.get('/auth/me', self.other).json()['nickname'], '测试昵称')
        self.assertEqual(initial_tokens, [dict(x) for x in db.fetchall('SELECT * FROM user_sessions ORDER BY user_id')])

    def test_profile_rejects_invalid_nickname_and_image_atomically(self):
        before = dict(db.fetchone('SELECT * FROM users WHERE id=?', (self.owner,)))
        for payload in ({'nickname': ' '}, {'nickname': '甲' * 41}, {'nickname': '坏\n昵称'},
                        {'avatar_data': 'data:image/svg+xml;base64,PHN2Zy8+'},
                        {'avatar_data': 'data:image/png;base64,not-an-image'},
                        {'nickname': '不应写入', 'avatar_data': 'javascript:invalid'}):
            with self.subTest(payload=payload):
                response = self.client.patch('/auth/profile', headers=self.headers(), json=payload)
                self.assertIn(response.status_code, (400, 422), response.text)
                self.assertEqual(before, dict(db.fetchone('SELECT * FROM users WHERE id=?', (self.owner,))))

    def test_public_profile_memory_and_growth_require_actual_login(self):
        for path in ('/auth/me', '/profile/growth', '/profile/memories', '/profile/achievements', '/billing/usage?period=calendar_month'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        denied = self.client.patch('/auth/profile', json={'nickname':'不应保存'},
                                   headers={'Authorization': 'Bearer '+self.tokens[self.owner]})
        self.assertEqual(denied.status_code, 403)

    def test_owner_memory_edit_delete_persist_and_feed_subsequent_prompt(self):
        row = memory.save_explicit_preferences(self.owner, memory.extract_explicit_preferences('以后少用表情'))[0]
        mid = row['id']
        listed = self.get('/profile/memories')
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()['memories'][0]['value'], '少用表情')
        self.assertEqual(self.get('/profile/memories', self.other).json()['memories'], [])
        for method, payload in (('PATCH', {'value': '多用表情'}), ('DELETE', None)):
            denied = self.client.request(method, '/profile/memories/'+mid, headers=self.headers(self.other), json=payload)
            self.assertEqual(denied.status_code, 404, denied.text)
        changed = self.client.patch('/profile/memories/'+mid, headers=self.headers(), json={'value': '多用表情'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['memory']['id'], mid)
        self.assertTrue(changed.json()['ok'])
        self.assertIn('emoji:多用表情', memory.build_memory_prompt(self.owner, domain='美食'))
        self.assertEqual(memory.read_preferences(self.owner)['emoji'], '多用表情')
        response = self.client.delete('/profile/memories/'+mid, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.get('/profile/memories').json()['memories'], [])
        self.assertEqual(memory.read_preferences(self.owner), {})
        self.assertEqual(memory.build_memory_prompt(self.owner, domain='美食'), '')

    def test_legacy_preferences_summary_is_readonly_truthful_and_owner_scoped(self):
        db.execute('INSERT INTO user_learn(user_id,pref_key,pref_value,updated_at) VALUES(?,?,?,?)',
                   (self.owner, 'emoji', '少用表情', self.now.isoformat()))
        before = db._DB_PATH.read_bytes()
        result = self.get('/profile/memories')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['memories'], [])
        preferences = result.json()['preferences']
        self.assertEqual(len(preferences), 1)
        self.assertEqual(preferences[0]['source'], 'legacy_user_learn')
        self.assertFalse(preferences[0]['editable'])
        self.assertNotIn('id', preferences[0])
        self.assertEqual(self.get('/profile/memories', self.other).json()['preferences'], [])
        self.assertEqual(db._DB_PATH.read_bytes(), before)

    def test_growth_get_recovers_real_bound_result_without_writes_or_cross_user(self):
        rid, nid = self.original_generation()
        other_rid, _ = self.original_generation(self.other, score=91)
        before = db._DB_PATH.read_bytes()
        first = self.get('/profile/growth')
        self.assertEqual(first.status_code, 200, first.text)
        second = self.get('/profile/growth')
        self.assertEqual(first.json(), second.json())
        rows = first.json()['records']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['source_type'], rows[0]['source_id'], rows[0]['note_id']), ('generation', rid, nid))
        self.assertEqual(rows[0]['record_origin'], 'recoverable')
        self.assertFalse(rows[0]['persisted'])
        self.assertEqual(first.json()['stats']['best_score'], 73)
        self.assertNotIn(other_rid, first.text)
        self.assertNotIn('PRIVATE_SOURCE_NOT_A_GROWTH_FIELD', first.text)
        self.assertEqual(db._DB_PATH.read_bytes(), before)
        self.assertEqual(db.fetchall('SELECT * FROM growth_records'), [])
        self.assertEqual(db.fetchall('SELECT * FROM user_memories'), [])

    def test_saved_note_versions_are_owner_scoped(self):
        own, other = self.note(), self.note(self.other)
        listed = self.get('/notes').json()
        self.assertEqual([x['id'] for x in listed['notes']], [own])
        self.assertEqual(self.get('/notes/'+other+'/versions').status_code, 404)
        own_result = self.get('/notes/'+own+'/versions')
        self.assertEqual(own_result.status_code, 200, own_result.text)
        self.assertEqual([x['id'] for x in own_result.json()['versions']], [own])

    def test_account_export_archive_recovery_and_tracking_are_owner_scoped(self):
        expired = (self.now-timedelta(days=8)).isoformat()
        own = self.note(created=expired)
        other = self.note(self.other, created=expired)
        before = db._DB_PATH.read_bytes()
        exported = self.get('/account/export')
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn(own, exported.text)
        self.assertNotIn(other, exported.text)
        self.assertNotIn(self.tokens[self.owner], exported.text)
        self.assertNotIn('password_hash', exported.text)
        available = self.get('/account/archive/recovery')
        self.assertEqual(available.status_code, 200, available.text)
        self.assertEqual([x['content_id'] for x in available.json()['items']], [own])
        self.assertEqual(self.get('/notes/tracking').status_code, 200)
        self.assertEqual(db._DB_PATH.read_bytes(), before)
        denied = self.client.post('/account/archive/recover', headers=self.headers(), json={'content_type':'note', 'content_id':other})
        self.assertEqual(denied.status_code, 404, denied.text)
        recovered = self.client.post('/account/archive/recover', headers=self.headers(), json={'content_type':'note', 'content_id':own})
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertTrue(recovered.json()['ok'])
        self.assertEqual([x['id'] for x in self.get('/notes').json()['notes']], [own])

    def test_revoke_all_sessions_affects_only_authenticated_owner(self):
        response = self.client.post('/auth/sessions/revoke-all', headers=self.headers(), json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get('/auth/me').status_code, 401)
        self.assertEqual(self.get('/auth/me', self.other).status_code, 200)

    def test_delete_single_note_preserves_other_versions_and_their_reports(self):
        original_rid, first = self.original_generation()
        second_rid, second = self.original_generation()
        db.execute('UPDATE notes SET parent_id=?,version=2 WHERE id=?', (first, second))
        memory.add_context(self.owner, '第一版素材', source_note_id=first)
        memory.add_context(self.owner, '第二版素材', source_note_id=second)
        memory.add_context(self.owner, '未归属历史')
        foreign = self.client.delete('/notes/'+second, headers=self.headers(self.other))
        self.assertEqual(foreign.status_code, 404, foreign.text)
        response = self.client.delete('/notes/'+second, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(db.fetchone('SELECT id FROM chat_sessions WHERE id=?', (original_rid,)))
        self.assertIsNone(db.fetchone('SELECT id FROM chat_sessions WHERE id=?', (second_rid,)))
        self.assertEqual([x['id'] for x in self.get('/notes').json()['notes']], [first])
        contexts = [r['content'] for r in memory.recall(self.owner, 'context')]
        self.assertIn('第一版素材', contexts)
        self.assertIn('未归属历史', contexts)
        self.assertNotIn('第二版素材', contexts)
        recovery = self.client.post('/account/archive/recover', headers=self.headers(), json={'content_type':'note','content_id':second})
        self.assertEqual(recovery.status_code, 400, recovery.text)
        # A later primary purge must not reintroduce the family-wide deletion.
        after_retention = self.now + timedelta(days=31)
        with mock.patch.object(db, '_retention_now', return_value=after_retention):
            purged = api._retention.process_due_content_purges(now=after_retention)
        self.assertIn('note:'+second, purged)
        self.assertIsNone(db.fetchone('SELECT id FROM notes WHERE id=?', (second,)))
        self.assertIsNotNone(db.fetchone('SELECT id FROM chat_sessions WHERE id=?', (original_rid,)))
        self.assertIsNotNone(db.fetchone('SELECT id FROM notes WHERE id=?', (first,)))

    def test_default_family_cleanup_preserves_existing_purge_contract(self):
        first_rid, first = self.original_generation()
        second_rid, second = self.original_generation()
        db.execute('UPDATE notes SET parent_id=?,version=2 WHERE id=?', (first, second))
        with db.transaction(write=True) as tx:
            api._retention.delete_note_derivatives_with_storage(tx, second, self.owner)
        self.assertIsNone(db.fetchone('SELECT id FROM chat_sessions WHERE id IN (?,?)', (first_rid, second_rid)))

    def test_calendar_month_usage_has_real_utc_bounds_and_owner_counts(self):
        clock = datetime(2026, 9, 19, tzinfo=timezone.utc)
        for uid, date in ((self.owner, '2026-08-31T23:59:59+00:00'),
                          (self.owner, '2026-09-01T00:00:00+00:00'),
                          (self.owner, '2026-10-01T00:00:00+00:00'),
                          (self.other, '2026-09-12T00:00:00+00:00')):
            db.execute('INSERT INTO usage_records(id,user_id,operation,recorded_at) VALUES(?,?,?,?)',
                       (str(uuid4()), uid, 'generate', date))
        before = db._DB_PATH.read_bytes()
        with mock.patch.object(usage_reporting, 'datetime') as now:
            now.now.return_value = clock
            reply = self.get('/billing/usage?period=calendar_month')
        self.assertEqual(reply.status_code, 200, reply.text)
        data = reply.json()
        self.assertEqual(data['window']['kind'], 'calendar_month')
        self.assertEqual(data['window']['start'], '2026-09-01T00:00:00+00:00')
        self.assertEqual(data['window']['end'], '2026-10-01T00:00:00+00:00')
        self.assertEqual(data['accounting']['business']['recorded'], 1)
        self.assertEqual(db._DB_PATH.read_bytes(), before)
        for query in ('period=unknown', 'days=0', 'days=367'):
            self.assertEqual(self.get('/billing/usage?'+query).status_code, 400)


if __name__ == '__main__':
    unittest.main()
