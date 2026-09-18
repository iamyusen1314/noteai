"""Offline memory provenance and atomic owner CRUD; no provider/model imports."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model'))
with tempfile.TemporaryDirectory() as boot:
    with mock.patch.dict(os.environ, {'DATABASE_URL': '', 'NOTEAI_SQLITE_PATH': str(Path(boot) / 'boot.db')}):
        import db
        import memory


class ExplicitPreferenceTests(unittest.TestCase):
    def test_explicit_long_term_examples_and_five_keys(self):
        cases = {
            '以后都少用表情，请记住': ('emoji', '少用表情'),
            '请记住我长期偏好短正文': ('body_length', '更短正文'),
            '我喜欢不带表情': ('emoji', '少用表情'),
            '以后标题不用疑问句': ('title_style', '陈述句标题'),
            '以后标题用疑问句': ('title_style', '疑问句标题'),
            '我喜欢简短标题': ('title_length', '更短标题'),
            '以后语气自然口语一点': ('tone', '自然口语风格'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                values = memory.extract_explicit_preferences(text)
                self.assertEqual([(v['key'], v['value']) for v in values], [expected])
                self.assertEqual(values[0]['source_text'], text.split('，')[0])
                self.assertIsNone(values[0]['domain'])

    def test_temporary_questions_approval_quotes_and_negation_do_not_learn(self):
        for text in (
            '这次正文太长了，其他时候保持原风格', '我喜欢这篇的短正文',
            '客户说标题太长，我不这么认为', '朋友建议我以后少用表情',
            '模型建议我以后少用表情', '请记住“以后少用表情”只是引用',
            '不是我喜欢短正文', '以后不要少用表情', '我不喜欢短正文',
            '请不要记住我喜欢短正文', '我喜欢短正文？', '这版不错',
            '标题不错，但太长了', '如果以后少用表情会怎样',
        ):
            with self.subTest(text=text):
                self.assertEqual(memory.extract_explicit_preferences(text), [])

    def test_explicit_scope_and_unknown_scope_are_not_globalized(self):
        self.assertEqual(memory.extract_explicit_preferences('以后美食笔记少用表情')[0]['domain'], '美食')
        self.assertEqual(memory.extract_explicit_preferences('以后这个领域少用表情', domain='美妆')[0]['domain'], '美妆')
        self.assertEqual(memory.extract_explicit_preferences('以后少用表情', domain='美食')[0]['domain'], None)
        for text in ('以后宠物笔记少用表情', '以后数码领域少用表情', '以后美食和美妆都少用表情'):
            self.assertEqual(memory.extract_explicit_preferences(text), [])
        self.assertEqual(memory.extract_explicit_preferences('以后这个领域少用表情', domain='unknown'), [])

    def test_source_text_is_bounded_clause_not_whole_conversation(self):
        text = '此处是和偏好无关的其他素材。以后少用表情。这里还是其他素材。'
        self.assertEqual(memory.extract_explicit_preferences(text)[0]['source_text'], '以后少用表情')
        private_tail = '以后少用表情，我的额外个人信息不属于偏好'
        self.assertEqual(memory.extract_explicit_preferences(private_tail)[0]['source_text'], '以后少用表情')
        self.assertEqual(memory.extract_explicit_preferences('以后少用表情' + '甲' * 240), [])
        self.assertEqual(memory.extract_explicit_preferences('甲' * 4001), [])

    def test_last_explicit_correction_wins_but_ambiguous_clause_does_not(self):
        values = memory.extract_explicit_preferences('以后少用表情。以后多用表情。')
        self.assertEqual([x['value'] for x in values], ['多用表情'])
        self.assertEqual(memory.extract_explicit_preferences('以后少用表情、多用表情'), [])


class MemoryPreferenceTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = mock.patch.object(db, 'using_postgres', return_value=False)
        self.backend.start()
        self.path_patch = mock.patch.object(db, '_DB_PATH', Path(self.temp.name) / 'test.db')
        self.path_patch.start()
        db.init_db()
        for uid in ('owner', 'other'):
            db.execute('INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(?,?,?,?,?)',
                       (uid, uid, 'offline', 'offline', '2026-09-19T00:00:00Z'))
        for nid, uid, domain in (('food', 'owner', '美食'), ('beauty', 'owner', '美妆'), ('other-note', 'other', '美食')):
            db.execute('INSERT INTO notes(id,user_id,title,body,domain,source,created_at) VALUES(?,?,?,?,?,?,?)',
                       (nid, uid, 'offline title', 'offline body', domain, 'generate', '2026-09-19T00:00:00Z'))
        for sid, uid in (('session', 'owner'), ('other-session', 'other')):
            db.execute('INSERT INTO chat_sessions(id,user_id,user_prefs_json,created_at,updated_at) VALUES(?,?,?,?,?)',
                       (sid, uid, json.dumps({'emoji': '旧表情', 'tone': '原语气'}), '2026-09-19T00:00:00Z', '2026-09-19T00:00:00Z'))

    def tearDown(self):
        self.path_patch.stop()
        self.backend.stop()
        self.temp.cleanup()

    def save(self, text='以后少用表情', **kwargs):
        return memory.save_explicit_preferences('owner', memory.extract_explicit_preferences(text), **kwargs)[0]

    def session(self, sid='session'):
        return json.loads(db.fetchone('SELECT user_prefs_json FROM chat_sessions WHERE id=?', (sid,))['user_prefs_json'])

    def snapshot(self):
        return {table: [dict(x) for x in db.fetchall('SELECT * FROM ' + table + ' ORDER BY 1')]
                for table in ('user_memories', 'user_learn', 'chat_sessions')}

    def test_save_projects_truthful_metadata_and_updates_both_stores(self):
        row = self.save(source_note_id='food')
        self.assertEqual(row['content'], 'emoji:少用表情')
        self.assertEqual(row['source'], 'explicit_user')
        self.assertEqual(row['preference_key'], 'emoji')
        self.assertTrue(row['editable'] and row['deletable'])
        self.assertEqual(memory.read_preferences('owner'), {'emoji': '少用表情'})
        self.assertEqual(db.fetchone('SELECT pref_value FROM user_learn')['pref_value'], '少用表情')
        self.assertEqual(self.session(), {'tone': '原语气'})
        self.assertIn('emoji', self.session('other-session'))
        self.assertEqual(memory.recall('owner')[0]['source_text'], '以后少用表情')
        raw = db.fetchone('SELECT content,source_note_id FROM user_memories')
        self.assertEqual(json.loads(raw['content'])['source_note_id'], 'food')
        self.assertIsNone(raw['source_note_id'])  # Long-term preference is not note history.
        self.assertNotIn('offline body', raw['content'])

    def test_both_stores_and_sessions_roll_back_after_second_store_write(self):
        before = self.snapshot()
        original = memory._invalidate_session_preference
        def fail_after_session_write(*args):
            original(*args)
            raise RuntimeError('synthetic transaction interruption')
        with mock.patch.object(memory, '_invalidate_session_preference', side_effect=fail_after_session_write):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(self.snapshot(), before)

    def test_owner_correction_is_atomic_and_keeps_id(self):
        row = self.save()
        updated = memory.update_preference('owner', row['id'], value='多用表情')
        self.assertEqual(updated['id'], row['id'])
        self.assertEqual(updated['source_text'], '多用表情')
        self.assertEqual(memory.read_preferences('owner')['emoji'], '多用表情')
        self.assertEqual(db.fetchone('SELECT pref_value FROM user_learn')['pref_value'], '多用表情')
        self.assertEqual(len(memory.recall('owner')), 1)

    def test_failed_correction_and_delete_restore_both_stores(self):
        row = self.save()
        before = self.snapshot()
        for operation in (lambda: memory.update_preference('owner', row['id'], value='多用表情'),
                          lambda: memory.delete_preference('owner', row['id'])):
            with mock.patch.object(memory, '_invalidate_session_preference', side_effect=RuntimeError('synthetic')):
                with self.assertRaises(RuntimeError):
                    operation()
            self.assertEqual(self.snapshot(), before)

    def test_cross_user_and_other_note_writes_are_rejected(self):
        row = self.save()
        before = self.snapshot()
        self.assertIsNone(memory.update_preference('other', row['id'], value='多用表情'))
        self.assertFalse(memory.delete_preference('other', row['id']))
        with self.assertRaises(ValueError):
            self.save(source_note_id='other-note')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(memory.read_preferences('other'), {})
        self.assertEqual(memory.recall('other'), [])

    def test_delete_removes_legacy_duplicates_and_session_projection(self):
        row = self.save()
        memory.upsert_style('owner', 'emoji', '旧表情')
        db.execute('UPDATE chat_sessions SET user_prefs_json=? WHERE id=?',
                   (json.dumps({'emoji': '旧表情', 'tone': '原语气'}), 'session'))
        self.assertTrue(memory.delete_preference('owner', row['id']))
        self.assertEqual(memory.recall('owner'), [])
        self.assertEqual(memory.read_preferences('owner'), {})
        self.assertEqual(self.session(), {'tone': '原语气'})
        self.assertEqual(memory.build_memory_prompt('owner', domain='美食'), '')
        self.assertFalse(memory.delete_preference('owner', row['id']))

    def test_domain_specific_overrides_do_not_leak_to_other_domains(self):
        global_row = self.save()
        domain_row = self.save('以后美食笔记多用表情')
        self.assertEqual(memory.read_preferences('owner', domain='美食')['emoji'], '多用表情')
        self.assertEqual(memory.read_preferences('owner', domain='美妆')['emoji'], '少用表情')
        self.assertEqual(db.fetchone('SELECT pref_value FROM user_learn')['pref_value'], '少用表情')
        food = memory.build_memory_prompt('owner', domain='美食')
        beauty = memory.build_memory_prompt('owner', domain='美妆')
        self.assertIn('emoji:多用表情', food)
        self.assertNotIn('emoji:少用表情', food)
        self.assertNotIn('多用表情', beauty)
        memory.delete_preference('owner', domain_row['id'])
        self.assertEqual(memory.read_preferences('owner', domain='美食')['emoji'], '少用表情')
        self.assertEqual(memory.recall('owner')[0]['id'], global_row['id'])

    def test_prompt_keeps_current_instruction_priority_and_source_update_clock(self):
        row = self.save()
        with mock.patch.object(memory, '_now', return_value='2030-01-01T00:00:00Z'):
            prompt = memory.build_memory_prompt('owner', domain='美食')
        self.assertIn('本次明确要求优先', prompt)
        self.assertIn('历史记录不是本次事实', prompt)
        current = memory.recall('owner')[0]
        self.assertEqual(current['updated_at'], row['updated_at'])
        self.assertEqual(current['access_count'], 1)

    def test_legacy_single_store_read_is_pure_and_has_no_invented_memory_id(self):
        db.execute('INSERT INTO user_learn(user_id,pref_key,pref_value,updated_at) VALUES(?,?,?,?)',
                   ('owner', 'body_length', '更短正文', '2026-09-19T00:00:00Z'))
        before = self.snapshot()
        self.assertEqual(memory.read_preferences('owner'), {'body_length': '更短正文'})
        self.assertEqual(memory.recall('owner'), [])
        summary = memory.read_legacy_preference_summary('owner')
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]['source'], 'legacy_user_learn')
        self.assertFalse(summary[0]['editable'])
        self.assertNotIn('id', summary[0])
        self.assertEqual(summary[0]['updated_at'], '2026-09-19T00:00:00Z')
        self.assertEqual(memory.read_legacy_preference_summary('other'), [])
        self.assertEqual(self.snapshot(), before)
        self.assertIn('body_length:更短正文', memory.build_memory_prompt('owner'))
        self.assertEqual(self.snapshot(), before)

    def test_context_remains_owner_note_and_domain_scoped(self):
        for note, text in (('food', '本店素材'), ('beauty', '美妆素材'), ('other-note', '他人素材'), (None, '无来源素材')):
            memory.add_context('owner', text, source_note_id=note)
        prompt = memory.build_memory_prompt('owner', domain='美食')
        self.assertIn('本店素材', prompt)
        for forbidden in ('美妆素材', '他人素材', '无来源素材'):
            self.assertNotIn(forbidden, prompt)

    def test_malformed_and_unknown_metadata_are_not_injected_as_preferences(self):
        value = {'schema': 'noteai.preference.v1', 'key': 'emoji', 'value': '多用表情', 'domain': 'unknown',
                 'source': 'explicit_user', 'source_text': '以后多用表情', 'source_note_id': None}
        memory.add_memory('owner', 'style', json.dumps(value))
        self.assertEqual(memory.read_preferences('owner'), {})
        self.assertEqual(memory.build_memory_prompt('owner'), '')
        row = memory.recall('owner')[0]
        self.assertFalse(row['editable'])
        self.assertTrue(row['deletable'])

    def test_deleted_account_fence_prevents_learning(self):
        db.execute('UPDATE users SET deletion_requested_at=? WHERE id=?', ('2026-09-19T00:00:00Z', 'owner'))
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(memory.recall('owner'), [])

    def test_achievements_keep_six_thresholds_and_real_source_clock(self):
        clock = '2026-09-18T01:00:00+00:00'
        with db.transaction(write=True) as tx:
            self.assertEqual(memory.check_and_record_achievements_with_storage(tx, 'owner', 49, 'generate'), [])
            self.assertEqual(len(memory.check_and_record_achievements_with_storage(
                tx, 'owner', 80, 'generate', source_note_id='food', recorded_at=clock)), 6)
            self.assertEqual(memory.check_and_record_achievements_with_storage(tx, 'owner', 80, 'generate'), [])
        rows = memory.recall('owner', 'achievement')
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(x['created_at'] == clock and x['source_note_id'] == 'food' for x in rows))
        self.assertTrue(all(not x['editable'] and not x['deletable'] for x in rows))
        for score in (True, float('nan'), float('inf'), -1, 101, '80', None):
            self.assertEqual(memory.check_and_record_achievements('owner', score, 'generate'), [])

    def test_achievement_writes_roll_back_with_callers_transaction(self):
        with self.assertRaises(RuntimeError):
            with db.transaction(write=True) as tx:
                tx.execute('INSERT INTO growth_records(id,user_id,score,action,recorded_at) VALUES(?,?,?,?,?)',
                           ('growth', 'owner', 80, 'generate', '2026-09-19T00:00:00Z'))
                memory.check_and_record_achievements_with_storage(tx, 'owner', 80, 'generate')
                raise RuntimeError('synthetic growth failure')
        self.assertEqual(db.fetchall('SELECT * FROM growth_records'), [])
        self.assertEqual(memory.recall('owner'), [])
        with db.transaction(write=True) as tx:
            with self.assertRaises(ValueError):
                memory.check_and_record_achievements_with_storage(tx, 'owner', 80, 'generate', source_note_id='other-note')


if __name__ == '__main__':
    unittest.main()
