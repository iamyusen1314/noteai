"""Provider-free Tracking management through the real public API boundary."""
import re
from unittest import mock
import unittest
from uuid import uuid4

from tests import test_product_integrity_api as fixture

api, db = fixture.api, fixture.db


class TrackingPublicManagementTests(unittest.TestCase):
    setUp = fixture.ProductIntegrityApiTests.setUp
    headers = fixture.ProductIntegrityApiTests.headers
    note = fixture.ProductIntegrityApiTests.note

    def tracking(self, user=None, *, status='needs_manual', active=False):
        uid, tid = user or self.owner, str(uuid4())
        nid = self.note(uid)
        xhs_id = tid.replace('-', '')[:24]
        db.execute(
            'INSERT INTO tracked_notes(id,user_id,source_note_id,source_root_note_id,'
            'xhs_url,xhs_note_id,note_title,domain,submitted_at,status,active_attempt_id,'
            'claim_token,claim_expires_at,predicted_ces) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, uid, nid, nid, 'https://www.xiaohongshu.com/explore/'+xhs_id+'?xsec_token=PRIVATE',
             xhs_id, '本人原笔记', '美食', self.now.isoformat(), status,
             None, 'PRIVATE_CLAIM', self.now.isoformat(), 73))
        if active:
            attempt = str(uuid4())
            db.execute('INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,admitted_at) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (attempt, tid, uid, str(uuid4()), '7d', 'started', self.now.isoformat()))
            db.execute('UPDATE tracked_notes SET active_attempt_id=? WHERE id=?', (attempt, tid))
        return tid, nid

    def row(self, tid):
        row = db.fetchone('SELECT * FROM tracked_notes WHERE id=?', (tid,))
        return dict(row) if row else None

    def fill(self, tid, *, user=None, payload=None):
        return self.client.post('/notes/tracking/'+tid+'/fill', headers=self.headers(user),
                                json=payload if payload is not None else
                                {'likes': 120, 'saves': 80, 'comments': 12, 'views': 900})

    def counts(self):
        return {table: db.fetchone('SELECT COUNT(*) AS c FROM '+table)['c']
                for table in ('growth_records', 'user_memories', 'tracking_provider_attempts',
                              'usage_records', 'credit_transactions')}

    def test_detail_is_owner_only_and_does_not_expose_claims_or_url_credentials(self):
        tid, nid = self.tracking(active=True)
        response = self.client.get('/notes/tracking/'+tid, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(detail['source_note_id'], nid)
        self.assertEqual(detail['provider_attempt_state'], 'in_progress')
        self.assertNotIn('PRIVATE', response.text)
        for key in ('claim_token', 'claim_expires_at', 'active_attempt_id'):
            self.assertNotIn(key, detail)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/notes/tracking/'+tid,
                                       headers=self.headers(self.other)).status_code, 404)
        self.assertEqual(self.client.get('/notes/tracking/'+str(uuid4()),
                                       headers=self.headers()).status_code, 404)

    def test_manual_fill_persists_real_manual_source_once_without_billing_or_provider(self):
        tid, nid = self.tracking()
        before = self.counts()
        response = self.fill(tid)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['ok'])
        row = self.client.get('/notes/tracking/'+tid, headers=self.headers()).json()
        self.assertEqual((row['status'], row['manual_filled'], row['evidence_source']),
                         ('complete', 1, 'manual'))
        self.assertEqual((row['likes_7d'], row['saves_7d'], row['comments_7d']), (120, 80, 12))
        self.assertFalse(row['training_eligible'])
        growth = db.fetchone('SELECT * FROM growth_records WHERE user_id=?', (self.owner,))
        memory = db.fetchone('SELECT * FROM user_memories WHERE user_id=?', (self.owner,))
        self.assertEqual((growth['note_id'], growth['action']), (nid, 'url_track'))
        self.assertEqual(memory['source_note_id'], nid)
        self.assertEqual(self.counts(), {**before, 'growth_records': before['growth_records']+1,
                                        'user_memories': before['user_memories']+1})
        completed = self.row(tid)
        self.assertEqual(self.fill(tid).status_code, 409)
        self.assertEqual(self.row(tid), completed)
        self.assertEqual(self.counts()['growth_records'], before['growth_records']+1)
        self.assertEqual(self.counts()['user_memories'], before['user_memories']+1)

    def test_manual_fill_other_owner_and_unavailable_states_are_rejected(self):
        tid, _ = self.tracking(self.other)
        before = self.row(tid)
        self.assertEqual(self.fill(tid).status_code, 404)
        self.assertEqual(self.row(tid), before)
        for status, active in (('pending', False), ('complete', False), ('checking_7d', False),
                               ('needs_manual', True), ('failed', True)):
            with self.subTest(status=status, active=active):
                tid, _ = self.tracking(status=status, active=active)
                before = self.row(tid)
                self.assertEqual(self.fill(tid).status_code, 409)
                self.assertEqual(self.row(tid), before)
        failed, _ = self.tracking(status='failed')
        self.assertEqual(self.fill(failed).status_code, 200)

    def test_invalid_counts_and_claimed_crawler_source_do_not_write(self):
        tid, _ = self.tracking()
        before, counts = self.row(tid), self.counts()
        for payload in ({'likes': -1}, {'saves': 2147483648}, {'comments': 'invalid'},
                        {'views': -1}, {'evidence_source': 'crawler'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.fill(tid, payload=payload).status_code, 422)
                self.assertEqual(self.row(tid), before)
                self.assertEqual(self.counts(), counts)

    def test_manual_effect_failure_rolls_back_the_entire_existing_transaction(self):
        tid, _ = self.tracking()
        before, counts = self.row(tid), self.counts()
        with mock.patch.object(api._memory, '_add_memory_with_storage', side_effect=RuntimeError('offline failure')):
            with self.assertRaises(RuntimeError):
                self.fill(tid)
        self.assertEqual(self.row(tid), before)
        self.assertEqual(self.counts(), counts)

    def test_delete_removes_only_own_tracking_and_remains_idempotent(self):
        tid, nid = self.tracking()
        self.assertEqual(self.fill(tid).status_code, 200)
        counts = self.counts()
        other_tid, _ = self.tracking(self.other)
        other_before = self.row(other_tid)
        for target in (other_tid, tid, tid):
            response = self.client.delete('/notes/tracking/'+target, headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {'ok': True})
        self.assertIsNone(self.row(tid))
        self.assertEqual(self.row(other_tid), other_before)
        self.assertIsNotNone(db.fetchone('SELECT id FROM notes WHERE id=? AND user_id=?', (nid, self.owner)))
        self.assertEqual(self.counts(), counts)

    def test_delete_active_attempt_refuses_without_changing_tracking(self):
        tid, _ = self.tracking(active=True)
        before = self.row(tid)
        response = self.client.delete('/notes/tracking/'+tid, headers=self.headers())
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.row(tid), before)

    def test_auth_phone_and_consent_are_required_for_all_three_routes(self):
        tid, _ = self.tracking()
        routes = (('GET', '/notes/tracking/'+tid), ('DELETE', '/notes/tracking/'+tid),
                  ('POST', '/notes/tracking/'+tid+'/fill'))
        for method, path in routes:
            response = self.client.request(method, path, json={} if method == 'POST' else None,
                                           headers={'Origin': self.headers()['Origin']})
            self.assertEqual(response.status_code, 401, response.text)
        db.execute('UPDATE users SET phone_verified_at=NULL WHERE id=?', (self.owner,))
        for method, path in routes:
            self.assertEqual(self.client.request(method, path, headers=self.headers(),
                             json={} if method == 'POST' else None).status_code, 403)
        db.execute('UPDATE users SET phone_verified_at=? WHERE id=?', (self.now.isoformat(), self.owner))
        db.execute('DELETE FROM user_contract_acceptances WHERE user_id=?', (self.owner,))
        for method, path in routes:
            self.assertEqual(self.client.request(method, path, headers=self.headers(),
                             json={} if method == 'POST' else None).status_code, 403)

    def test_write_origin_json_and_product_mode_boundaries_remain(self):
        tid, _ = self.tracking()
        for method, path in (('POST', '/notes/tracking/'+tid+'/fill'), ('DELETE', '/notes/tracking/'+tid)):
            for origin in (None, 'https://unrelated.example.invalid'):
                headers = self.headers()
                headers.pop('Origin')
                if origin:
                    headers['Origin'] = origin
                self.assertEqual(self.client.request(method, path, headers=headers,
                                 json={} if method == 'POST' else None).status_code, 403)
        self.assertEqual(self.client.post('/notes/tracking/'+tid+'/fill', headers=self.headers(),
                                         content='{}').status_code, 415)
        with mock.patch.dict(fixture.os.environ, {'NOTEAI_PUBLIC_PRODUCT': '0'}):
            for method, path in (('GET', '/notes/tracking/'+tid), ('DELETE', '/notes/tracking/'+tid),
                                 ('POST', '/notes/tracking/'+tid+'/fill')):
                self.assertEqual(self.client.request(method, path, headers=self.headers(), json={}).status_code, 404)
        self.assertEqual(self.client.post('/notes/track-url', headers=self.headers(), json={}).status_code, 403)

    def test_capabilities_separate_manual_management_from_automatic_collection(self):
        for enabled in ('1', '0'):
            with mock.patch.dict(fixture.os.environ, {'NOTEAI_PUBLIC_PRODUCT': enabled}):
                status = api._public_account.service_status()
                self.assertFalse(status['tracking_open'])
                for key in ('tracking_read_open', 'tracking_manual_open', 'tracking_delete_open'):
                    self.assertIs(status[key], enabled == '1')

    def test_literal_routes_match_nginx_and_do_not_enable_automatic_tracking(self):
        tid = str(uuid4())
        source = (fixture.ROOT/'deploy/production/public-account.locations.conf').read_text()
        route = '/notes/tracking/'+tid
        for suffix, methods in (('', {'GET', 'DELETE'}), ('/fill', {'POST'})):
            path = route+suffix
            blocks = re.findall(r'location ~ "([^"\n]+)" \{\n(.*?)\n\}', source, re.S)
            matches = [body for pattern, body in blocks if re.fullmatch(pattern, path)]
            self.assertEqual(len(matches), 1)
            self.assertEqual(set(re.search(r'limit_except ([A-Z ]+) \{', matches[0]).group(1).split()), methods)
            self.assertIn('include /etc/nginx/noteai-product-proxy.conf;', matches[0])
            for method in ('GET', 'POST', 'DELETE', 'PUT', 'PATCH'):
                self.assertEqual(api._public_product.allowed_route(method, path), method in methods)
        for path in (route+'/', route.upper(), '/notes/tracking/not-an-id', route+'/fill/'):
            for method in ('GET', 'POST', 'DELETE'):
                self.assertFalse(api._public_product.allowed_route(method, path), (method, path))
        encoded = '/notes/tracking/%'+format(ord(tid[0]), '02x')+tid[1:]
        self.assertEqual(self.client.get(encoded, headers=self.headers()).status_code, 404)

    def manual_create(self, source=None, **changes):
        payload = {'collection_mode': 'manual', 'source_note_id': source,
                   'xhs_url': 'https://www.xiaohongshu.com/explore/' + uuid4().hex[:24]}
        payload.update(changes)
        return self.client.post('/notes/track-url', headers=self.headers(), json=payload)

    def test_manual_create_to_fill_detail_and_delete_uses_owned_original_note(self):
        nid = self.note(score=73)
        counts = self.counts()
        response = self.manual_create(nid, note_title='不能替换来源标题', domain='旅游', predicted_ces=99)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        tid = result['id']
        self.assertEqual((result['status'], result['source_note_id'], result['source_root_note_id']),
                         ('needs_manual', nid, nid))
        self.assertIsNone(result['next_check_at'])
        self.assertIn('未经平台核验', result['message'])
        row = self.row(tid)
        self.assertEqual((row['note_title'], row['domain'], row['predicted_ces']),
                         ('离线真实保存标题', '美食', 73))
        self.assertEqual((row['evidence_source'], row['max_attempts'], row['attempt_count']), ('manual', 1, 0))
        for key in ('active_attempt_id', 'claim_token', 'claim_expires_at', 'next_check_at'):
            self.assertIsNone(row[key])
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.fill(tid).status_code, 200)
        detail = self.client.get('/notes/tracking/'+tid, headers=self.headers()).json()
        self.assertEqual((detail['status'], detail['evidence_source']), ('complete', 'manual'))
        self.assertEqual(self.client.delete('/notes/tracking/'+tid, headers=self.headers()).status_code, 200)
        self.assertIsNotNone(db.fetchone('SELECT id FROM notes WHERE id=?', (nid,)))
        self.assertEqual(self.counts()['tracking_provider_attempts'], counts['tracking_provider_attempts'])

    def test_manual_create_preserves_missing_prediction_and_same_owner_dedup(self):
        nid = self.note(score=None)
        url = 'https://www.xiaohongshu.com/explore/' + uuid4().hex[:24]
        result = self.manual_create(nid, xhs_url=url+'?xsec_token=discard').json()
        row = self.row(result['id'])
        self.assertIsNone(row['predicted_ces'])
        self.assertEqual(row['xhs_url'], url)
        self.assertEqual(self.manual_create(nid, xhs_url=url).status_code, 409)
        self.assertEqual(db.fetchone('SELECT COUNT(*) AS c FROM tracked_notes')['c'], 1)

    def test_manual_create_requires_visible_owned_unambiguous_source_and_valid_url(self):
        own, foreign = self.note(), self.note(self.other)
        for payload, code in (({}, 422), ({'source_note_id': foreign}, 404),
                              ({'source_note_id': str(uuid4())}, 404),
                              ({'source_note_id': own, 'source_note_version_id': foreign}, 422),
                              ({'source_note_id': own, 'xhs_url': 'https://xhslink.com/abc'}, 400),
                              ({'source_note_id': own, 'source_session_id': str(uuid4())}, 404)):
            with self.subTest(payload=payload):
                response = self.manual_create(**payload)
                self.assertEqual(response.status_code, code, response.text)
        self.assertEqual(self.client.delete('/notes/'+own, headers=self.headers()).status_code, 200)
        self.assertEqual(self.manual_create(own).status_code, 404)
        self.assertEqual(db.fetchone('SELECT COUNT(*) AS c FROM tracked_notes')['c'], 0)

    def test_automatic_and_missing_mode_are_denied_before_existing_track_handler(self):
        nid = self.note()
        with mock.patch.object(api, '_tracking_next_check_at', side_effect=AssertionError('must not schedule')):
            self.assertEqual(self.manual_create(nid).status_code, 200)
            for mode in ('automatic', 'invalid', None):
                payload = {'source_note_id': nid, 'xhs_url': 'https://www.xiaohongshu.com/explore/'+uuid4().hex[:24]}
                if mode is not None:
                    payload['collection_mode'] = mode
                response = self.client.post('/notes/track-url', headers=self.headers(), json=payload)
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(db.fetchone('SELECT COUNT(*) AS c FROM tracked_notes')['c'], 1)
        with mock.patch.dict(fixture.os.environ, {'NOTEAI_PUBLIC_PRODUCT': '0'}):
            self.assertEqual(self.manual_create(nid).status_code, 404)

    def test_manual_record_is_not_a_due_collection_candidate(self):
        # Use the existing selector only: no worker, provider or dispatch.
        import crawler
        nid = self.note()
        result = self.manual_create(nid, published_at='2020-01-01T00:00:00+00:00').json()
        self.assertEqual(crawler._claim_due_tracking_notes(1), [])
        self.assertIsNone(self.row(result['id'])['claim_token'])

    def test_manual_create_nginx_is_post_only_and_uses_product_auth_boundary(self):
        source = (fixture.ROOT/'deploy/production/public-account.locations.conf').read_text()
        body = re.search(r'location = /notes/track-url \{\n(.*?)\n\}', source, re.S).group(1)
        self.assertIn('limit_except POST { deny all; }', body)
        self.assertIn('include /etc/nginx/noteai-product-proxy.conf;', body)
        for method in ('GET', 'DELETE', 'PUT', 'PATCH'):
            self.assertFalse(api._public_product.allowed_route(method, '/notes/track-url'))
        self.assertEqual(self.client.post('/notes/track-url', headers={'Origin': self.headers()['Origin']},
                                         json={'collection_mode': 'manual'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
