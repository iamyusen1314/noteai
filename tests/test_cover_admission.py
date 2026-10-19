"""Offline acceptance scope, shared guard and unchanged upload TTL contracts."""
import io
import uuid
import unittest
from unittest import mock

from PIL import Image
from tests import test_cover_jobs as fixtures
import billing
import cover_jobs
import cover_settings
import db
import private_storage
import public_product


class CoverAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.net = mock.patch('socket.socket.connect', side_effect=AssertionError('offline only'))
        self.net.start()
        self.markers = []

    def tearDown(self):
        for variable, marker in reversed(self.markers):
            variable.reset(marker)
        self.net.stop()
        self.fixture.tearDown()

    def invocation(self, *, formal=False, budget=None):
        policy = {**self.fixture.policy, 'budget_id': cover_settings.FORMAL_BUDGET_ID} if formal else self.fixture.policy
        job = self.fixture.submit(policy_snapshot=policy, quote_version=cover_jobs.policy_quote_version(policy))
        usage = db.fetchone('SELECT usage_id FROM cover_jobs WHERE id=?', (job['job_id'],))['usage_id']
        selected = budget or policy['budget_id']
        value = public_product.Invocation(self.fixture.user, job['job_id'], route='/covers', budget_id=selected)
        self.markers.append((public_product._invocation, public_product._invocation.set(value)))
        self.markers.append((billing._ACTIVE_USAGE_ID, billing._ACTIVE_USAGE_ID.set(usage)))
        return selected

    def reserve(self, amount=600):
        return public_product._reserve_payload({'model': cover_settings.MODEL_ID,
            'provider': 'seedream', 'modality': 'image_generation', 'max_tokens': 0}, amount,
            require_metered=True)

    def test_acceptance_hard_budget_applies_even_owner_metered(self):
        budget = self.invocation()
        db.execute('UPDATE public_trial_budget SET reserved_milli_cny=99999 WHERE id=?', (budget,))
        with self.assertRaisesRegex(public_product.TrialProviderStopped, 'BUDGET_EXHAUSTED'):
            self.reserve(2)
        self.assertEqual(db.fetchone('SELECT count(*) FROM public_trial_calls')[0], 0)

    def test_acceptance_global_eighteen_call_cap_is_not_formal_lifetime_cap(self):
        budget = self.invocation()
        for _ in range(18):
            db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at) '
                "VALUES(?,?,?,'fixture','responded',0,?)", (str(uuid.uuid4()), budget, self.fixture.user, self.fixture.now.isoformat()))
        with self.assertRaisesRegex(public_product.TrialProviderStopped, 'COVER_CALL_LIMIT_REACHED'):
            self.reserve()
        formal = self.invocation(formal=True)
        db.execute('UPDATE public_trial_budget SET reserved_milli_cny=100001 WHERE id=?', (formal,))
        for _ in range(3):
            call = self.reserve()
            db.execute("UPDATE public_trial_calls SET state='responded',http_status=403 WHERE id=?", (call,))
        with self.assertRaisesRegex(public_product.TrialProviderStopped, 'COVER_CALL_LIMIT_REACHED'):
            self.reserve()
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?', (budget,))[0], 0)

    def test_cover_never_uses_old_website_budget(self):
        self.invocation(budget=public_product.BUDGET_ID)
        with self.assertRaisesRegex(public_product.TrialProviderStopped, 'COVER_REQUIRES_SEPARATE_BUDGET'):
            self.reserve()
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?', (public_product.BUDGET_ID,))[0], 0)

    def test_only_explicit_cover_lifecycle_extends_image_ttl(self):
        output = io.BytesIO()
        Image.new('RGB', (3, 3), 'blue').save(output, 'PNG')
        kwargs = dict(purpose='image', content_type='image/png', payload=output.getvalue(), item_count=1,
            ttl_seconds=cover_settings.RETENTION_SECONDS)
        with self.assertRaises(ValueError):
            private_storage.store_media_bytes(self.fixture.user, **kwargs)
        result = private_storage.store_media_bytes(self.fixture.user, lifecycle='cover_v1', **kwargs)
        self.assertTrue(result.expires_at)

