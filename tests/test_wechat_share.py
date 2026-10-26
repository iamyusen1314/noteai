"""Directed, provider-free sharing signer/cache and exact API-route contracts."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import wechat_share as share


CONFIG = share.Configuration('wx0123456789abcdef', 'fixturesecret0123456789abcdef0123')
URL = 'https://noteaipro.com/?from=wechat&x=%2F#report'


class WeChatShareTests(unittest.TestCase):
    def setUp(self):
        self.network = mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('real network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.now = 100.0
        self.calls = []

    def provider(self, method, path, payload):
        self.calls.append((method, path, payload))
        if method == 'POST':
            return {'access_token': 'fixture-access-token', 'expires_in': 7200}
        return {'errcode': 0, 'ticket': 'fixture-jsapi-ticket', 'expires_in': 7200}

    def service(self, provider=None):
        return share.ShareService(transport=provider or self.provider,
            clock=lambda: self.now, wall_clock=lambda: 1700000000, nonce=lambda: 'safeNonce123')

    def test_strict_page_validation_preserves_query_and_excludes_fragment(self):
        self.assertEqual(share.signing_url(URL), URL.split('#')[0])
        for url in ('http://noteaipro.com/', 'https://evil.test/', 'https://noteaipro.com.evil.test/',
                    'https://noteaipro.com@evil.test/', 'https://noteaipro.com:443/',
                    'https://noteaipro.com/admin/', 'https://noteaipro.com/covers/a/download',
                    'https://noteaipro.com/a6b.txt', 'https://noteaipro.com/../',
                    'https://noteaipro.com/%2f', 'https://noteaipro.com/\\evil',
                    'https://noteaipro.com/\n', 'https://noteaipro.com/?x=' + 'a' * 2048):
            with self.subTest(url=url[:80]), self.assertRaises(share.ShareURLInvalid):
                self.service().share_config(url, config=CONFIG)
        self.assertEqual(self.calls, [])
        self.assertEqual(share.signing_url('https://www.noteaipro.com/index.html?a=1'),
                         'https://www.noteaipro.com/index.html?a=1')

    def test_signature_exact_bytes_public_shape_and_cached_no_extra_request(self):
        service = self.service()
        result = service.share_config(URL, config=CONFIG)
        canonical = ('jsapi_ticket=fixture-jsapi-ticket&noncestr=safeNonce123'
                     '&timestamp=1700000000&url=https://noteaipro.com/?from=wechat&x=%2F')
        self.assertEqual(result, {'enabled': True, 'appId': CONFIG.app_id,
            'timestamp': 1700000000, 'nonceStr': 'safeNonce123',
            'signature': hashlib.sha1(canonical.encode()).hexdigest(),
            'jsApiList': ['updateAppMessageShareData', 'updateTimelineShareData']})
        self.assertEqual(self.calls[0], ('POST', '/cgi-bin/stable_token', {
            'grant_type': 'client_credential', 'appid': CONFIG.app_id,
            'secret': CONFIG.app_secret, 'force_refresh': False}))
        self.assertEqual(self.calls[1], ('GET',
            '/cgi-bin/ticket/getticket?access_token=fixture-access-token&type=jsapi', None))
        self.assertEqual(service.share_config(URL, config=CONFIG), result)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn(CONFIG.app_secret, json.dumps(result))
        self.assertNotIn('fixture-jsapi-ticket', json.dumps(result))
        self.assertNotIn(CONFIG.app_secret, repr(CONFIG))

    def test_missing_or_legacy_configuration_stays_closed_without_provider(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(share.ShareUnavailable, 'DISABLED'):
                share.configuration()
            os.environ.update(NOTEAI_WECHAT_SHARE_ENABLED='1', NOTEAI_WECHAT_SHARE_APP_ID=CONFIG.app_id,
                NOTEAI_WECHAT_SHARE_APP_SECRET=CONFIG.app_secret, NOTEAI_WECHAT_SHARE_TOKEN_MODE='legacy')
            with self.assertRaisesRegex(share.ShareUnavailable, 'NOT_CONFIGURED'):
                share.configuration()
            os.environ['NOTEAI_WECHAT_SHARE_TOKEN_MODE'] = 'stable'
            self.assertEqual(share.configuration(), CONFIG)
        self.assertEqual(self.calls, [])

    def test_concurrent_cold_misses_have_only_one_refresh(self):
        entered, release = threading.Event(), threading.Event()
        def provider(method, path, payload):
            if method == 'POST':
                entered.set()
                self.assertTrue(release.wait(3))
            return self.provider(method, path, payload)
        service = self.service(provider)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.share_config, URL, config=CONFIG)
            self.assertTrue(entered.wait(3))
            with self.assertRaisesRegex(share.ShareUnavailable, 'REFRESH_IN_PROGRESS'):
                service.share_config(URL, config=CONFIG)
            release.set()
            self.assertTrue(first.result(3)['enabled'])
        self.assertEqual(len(self.calls), 2)

    def test_failure_cooldown_and_ticket_failure_reuses_valid_token(self):
        fail_ticket = True
        def provider(method, path, payload):
            data = self.provider(method, path, payload)
            return {'errcode': 40014, 'errmsg': CONFIG.app_secret} if method == 'GET' and fail_ticket else data
        service = self.service(provider)
        with self.assertRaisesRegex(share.ShareUnavailable, '^WECHAT_SHARE_PROVIDER_UNAVAILABLE$'):
            service.share_config(URL, config=CONFIG)
        self.assertEqual(len(self.calls), 2)
        for _ in range(4):
            with self.assertRaisesRegex(share.ShareUnavailable, 'COOLDOWN'):
                service.share_config(URL, config=CONFIG)
        self.assertEqual(len(self.calls), 2)
        self.now += 61
        fail_ticket = False
        self.assertTrue(service.share_config(URL, config=CONFIG)['enabled'])
        self.assertEqual([call[0] for call in self.calls], ['POST', 'GET', 'GET'])

    def test_expiry_margin_and_configuration_change_do_not_reuse_wrong_ticket(self):
        service = self.service()
        service.share_config(URL, config=CONFIG)
        self.now += 7139
        service.share_config(URL, config=CONFIG)
        self.assertEqual(len(self.calls), 2)
        self.now += 1
        service.share_config(URL, config=CONFIG)
        self.assertEqual(len(self.calls), 4)
        service.share_config(URL, config=share.Configuration('wxabcdef0123456789', CONFIG.app_secret))
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(self.calls[-2][2]['appid'], 'wxabcdef0123456789')

    def test_request_rate_and_bucket_storage_are_bounded(self):
        service = self.service()
        for _ in range(60):
            service.share_config(URL, client_key='same-ip', config=CONFIG)
        with self.assertRaises(share.ShareRateLimited):
            service.share_config(URL, client_key='same-ip', config=CONFIG)
        for i in range(540):
            service.share_config(URL, client_key=str(i), config=CONFIG)
        with self.assertRaises(share.ShareRateLimited):
            service.share_config(URL, client_key='new-ip', config=CONFIG)
        self.assertLessEqual(len(service._buckets), 1024)
        self.assertEqual(len(self.calls), 2)
        self.now += 60
        self.assertTrue(service.share_config(URL, client_key='same-ip', config=CONFIG)['enabled'])

    def test_http_uses_fixed_tls_host_bounded_body_and_no_redirect(self):
        connection = mock.Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"ticket":"fixture-ticket","expires_in":7200}'
        with mock.patch.object(share.http.client, 'HTTPSConnection', return_value=connection) as client:
            result = share._request_json('POST', '/cgi-bin/stable_token', {'secret': 'fixture'})
            self.assertEqual(result['ticket'], 'fixture-ticket')
            args, kwargs = client.call_args
            self.assertEqual(args, ('api.weixin.qq.com', 443))
            self.assertEqual(kwargs['timeout'], 4)
            self.assertTrue(kwargs['context'].check_hostname)
            response.read.assert_called_once_with(share.MAX_RESPONSE_BYTES + 1)
            connection.close.assert_called_once()
        for status, body in ((302, b'{}'), (200, b'a' * (share.MAX_RESPONSE_BYTES + 1))):
            connection.reset_mock()
            response.status, response.read.return_value = status, body
            with mock.patch.object(share.http.client, 'HTTPSConnection', return_value=connection):
                with self.assertRaises(share.ShareUnavailable):
                    share._request_json('GET', '/fixed', None)
                self.assertEqual(connection.request.call_count, 1)

    def test_invalid_expiry_token_or_exception_has_safe_cooldown(self):
        cases = ({'access_token': 'fixture-token', 'expires_in': True},
                 {'access_token': 'fixture-token', 'expires_in': 30},
                 {'access_token': 'bad\nvalue', 'expires_in': 7200},
                 {'access_token': 'fixture-token', 'expires_in': 7201})
        for data in cases:
            service = self.service(lambda *_: data)
            with self.subTest(data=data), self.assertRaisesRegex(share.ShareUnavailable, '^WECHAT_SHARE_PROVIDER_UNAVAILABLE$'):
                service.share_config(URL, config=CONFIG)
        service = self.service(lambda *_: (_ for _ in ()).throw(RuntimeError(CONFIG.app_secret)))
        with self.assertRaises(share.ShareUnavailable) as error:
            service.share_config(URL, config=CONFIG)
        self.assertNotIn(CONFIG.app_secret, str(error.exception))


class WeChatShareRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use the exact new API declarations, without importing the full API,
        # dotenv, model artifacts, local/business DB or application startup.
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel, Field
        from starlette.concurrency import run_in_threadpool
        tree = ast.parse((ROOT / 'model/api.py').read_text())
        nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef))
                 and node.name in {'WeChatShareConfigInput', 'wechat_share_config'}]
        cls.app = FastAPI()
        scope = {'app': cls.app, 'BaseModel': BaseModel, 'Field': Field, 'Request': Request,
            'JSONResponse': JSONResponse, 'run_in_threadpool': run_in_threadpool, '_wechat_share': share,
            '_auth_request_fingerprint': lambda request: request.client.host}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'exact-new-api-route', 'exec'), scope)

    def test_anonymous_post_public_response_no_store_and_safe_503(self):
        from fastapi.testclient import TestClient
        with TestClient(self.app) as client:
            result = {'enabled': True, 'appId': CONFIG.app_id, 'timestamp': 1,
                'nonceStr': 'nonce', 'signature': 'a' * 40, 'jsApiList': list(share.JS_API_LIST)}
            with mock.patch.object(share, 'share_config', return_value=result) as signer:
                response = client.post('/wechat/share-config', json={'url': URL})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), result)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                signer.assert_called_once_with(URL, client_key='testclient')
                self.assertEqual(client.get('/wechat/share-config').status_code, 405)
            with mock.patch.object(share, 'share_config', side_effect=share.ShareUnavailable('WECHAT_SHARE_DISABLED')):
                response = client.post('/wechat/share-config', json={'url': URL})
                self.assertEqual(response.status_code, 503)
                self.assertFalse(response.json()['enabled'])
                self.assertEqual(response.headers['retry-after'], '60')
            with mock.patch.object(share, 'share_config', side_effect=share.ShareURLInvalid('private URL')):
                response = client.post('/wechat/share-config', json={'url': URL})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn('private URL', response.text)
            with mock.patch.object(share, 'share_config', side_effect=share.ShareRateLimited('WECHAT_SHARE_RATE_LIMITED')):
                self.assertEqual(client.post('/wechat/share-config', json={'url': URL}).status_code, 429)
            self.assertEqual(client.post('/wechat/share-config', json={'url': 123}).status_code, 422)
            self.assertEqual(client.post('/wechat/share-config', json={'url': 'a' * 2049}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
