import asyncio
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import crawler  # noqa: E402
import market_timing_worker  # noqa: E402
import scheduler_a  # noqa: E402
import spider_xhs_http as xhs  # noqa: E402


class FakeSigner:
    def __init__(self):
        self.calls = []

    def sign(self, **kwargs):
        self.calls.append(kwargs)
        result = {"xs": "signed", "xt": "123", "xs_common": "common"}
        if kwargs["needs_rap"]:
            result["x_rap_param"] = "rap"
        return result


def credentials():
    return xhs.SessionCredentials.from_records([
        {"name": "a1", "value": "SECRET_A1"},
        {"name": "web_session", "value": "SECRET_SESSION", "expires": 4102444800},
    ])


class SpiderXHSHTTPAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_CLOUD_RUNTIME": "0",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def adapter(self, responses):
        queue = list(responses)
        requests = []

        def handler(request):
            requests.append(request)
            status, payload = queue.pop(0)
            return httpx.Response(status, json=payload)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        signer = FakeSigner()
        adapter = xhs.SpiderXHSHTTPAdapter(
            credentials=credentials(), signer=signer, client=client
        )
        self.addCleanup(client.close)
        safety = mock.patch.object(xhs, "_assert_collection_allowed", return_value=None)
        safety.start()
        self.addCleanup(safety.stop)
        return adapter, signer, requests

    def test_six_read_only_capabilities_and_fixed_endpoints(self):
        adapter, signer, requests = self.adapter([
            (200, {"success": True, "data": {"items": [{"id": "h1"}], "cursor_score": ""}}),
            (200, {"success": True, "data": {"items": [{"keyword": "美食"}]}}),
            (200, {"success": True, "data": {"items": [{"id": "s1"}], "has_more": False}}),
            (200, {"success": True, "data": {"items": [{"note_card": {"title": "标题"}}]}}),
        ])

        self.assertEqual(adapter.session_health()["status"], "ready")
        self.assertEqual(adapter.homefeed()["items"][0]["id"], "h1")
        self.assertTrue(adapter.search_recommend("美食")["success"])
        self.assertEqual(adapter.search_notes("美食")["items"][0]["id"], "s1")
        detail = adapter.note_detail(
            "https://www.xiaohongshu.com/explore/0123456789abcdef?xsec_token=SECRET_TOKEN"
        )
        self.assertTrue(detail["success"])
        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/sns/web/v1/homefeed",
                "/api/sns/web/v1/search/recommend",
                "/api/sns/web/v1/search/notes",
                "/api/sns/web/v1/feed",
            ],
        )
        self.assertEqual(len(signer.calls), 4)
        self.assertTrue(signer.calls[-1]["needs_rap"])
        search_body = json.loads(requests[2].content.decode("utf-8"))
        self.assertEqual(
            [item["type"] for item in search_body["filters"]],
            [
                "sort_type",
                "filter_note_type",
                "filter_note_time",
                "filter_note_range",
                "filter_pos_distance",
            ],
        )
        self.assertEqual(requests[3].headers["xy-direction"], "13")

    def test_homefeed_pagination_stops_on_duplicate_cursor_and_caps_pages(self):
        adapter, _signer, requests = self.adapter([
            (200, {"success": True, "data": {"items": [{"id": "1"}], "cursor_score": "same"}}),
            (200, {"success": True, "data": {"items": [{"id": "2"}], "cursor_score": "same"}}),
        ])

        result = adapter.homefeed(max_pages=99, max_items=99)

        self.assertEqual([item["id"] for item in result["items"]], ["1", "2"])
        self.assertEqual(result["pages"], 2)
        self.assertEqual(len(requests), 2)

    def test_search_pagination_is_bounded(self):
        adapter, _signer, requests = self.adapter([
            (200, {"success": True, "data": {"items": [{"id": str(page)}], "has_more": True}})
            for page in range(3)
        ])

        result = adapter.search_notes("旅行", max_pages=999, max_items=60)

        self.assertEqual(result["pages"], 3)
        self.assertEqual(len(requests), 3)

    def test_write_methods_arbitrary_hosts_and_proxy_arguments_are_unavailable(self):
        adapter, signer, requests = self.adapter([])

        with self.assertRaisesRegex(xhs.XHSAdapterError, "operation_not_allowed"):
            adapter._request("DELETE", "/api/sns/web/v1/feed")
        with self.assertRaisesRegex(xhs.XHSAdapterError, "operation_not_allowed"):
            adapter._request("GET", "/api/sns/web/v1/user/selfinfo")
        with self.assertRaisesRegex(xhs.XHSAdapterError, "invalid_note_url"):
            adapter.note_detail("https://example.invalid/explore/0123456789abcdef")

        self.assertFalse(any("proxy" in parameter for parameter in inspect.signature(xhs.SpiderXHSHTTPAdapter).parameters))
        for method in ("homefeed", "search_recommend", "search_notes", "note_detail"):
            self.assertFalse(any("proxy" in parameter for parameter in inspect.signature(getattr(adapter, method)).parameters))
        self.assertFalse(hasattr(adapter, "publish"))
        self.assertFalse(hasattr(adapter, "login"))
        self.assertEqual(signer.calls, [])
        self.assertEqual(requests, [])

    def test_challenge_login_and_cooldown_fail_closed_with_secret_free_errors(self):
        cases = (
            (403, {"success": False}, "login_or_challenge_required"),
            (200, {"success": False, "msg": "请完成验证 challenge"}, "challenge"),
            (200, {"success": False, "msg": "访问过于频繁"}, "cooldown"),
            (200, {"success": False, "msg": "请先登录"}, "login_required"),
        )
        for status, payload, code in cases:
            with self.subTest(code=code):
                adapter, _signer, _requests = self.adapter([(status, payload)])
                with self.assertRaises(xhs.XHSAdapterError) as raised:
                    adapter.search_recommend("测试")
                self.assertEqual(raised.exception.code, code)
                rendered = str(raised.exception)
                self.assertNotIn("SECRET_A1", rendered)
                self.assertNotIn("SECRET_SESSION", rendered)

    def test_collection_lock_defaults_closed_before_client_signer_or_network(self):
        blocked_values = (None, "", "unexpected", "1", "true", "yes", "on")
        for value in blocked_values:
            with self.subTest(value=value):
                env = {
                    "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
                    "NOTEAI_RUNTIME_ROLE": "xhs-http",
                }
                if value is not None:
                    env["NOTEAI_XHS_COLLECTION_SUSPENDED"] = value
                signer = FakeSigner()
                client = mock.Mock()
                adapter = xhs.SpiderXHSHTTPAdapter(
                    credentials=credentials(), signer=signer, client=client
                )
                with mock.patch.dict(os.environ, env, clear=True):
                    with self.assertRaisesRegex(xhs.XHSAdapterError, "collection_suspended"):
                        adapter.search_recommend("测试")
                self.assertEqual(signer.calls, [])
                client.request.assert_not_called()

    def test_collection_lock_only_explicit_false_values_unlock_mocked_request(self):
        for value in ("0", "false", "off", "no", " FALSE "):
            with self.subTest(value=value):
                requests = []

                def handler(request):
                    requests.append(request)
                    return httpx.Response(200, json={"success": True, "data": {"items": []}})

                client = httpx.Client(transport=httpx.MockTransport(handler))
                self.addCleanup(client.close)
                signer = FakeSigner()
                adapter = xhs.SpiderXHSHTTPAdapter(
                    credentials=credentials(), signer=signer, client=client
                )
                with mock.patch.dict(os.environ, {
                    "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
                    "NOTEAI_XHS_COLLECTION_SUSPENDED": value,
                    "NOTEAI_RUNTIME_ROLE": "xhs-http",
                }, clear=True), mock.patch(
                    "xhs_acquisition.collection_safety_status",
                    return_value={"session_blocked": False},
                ):
                    result = adapter.search_recommend("测试")

                self.assertTrue(result["success"])
                self.assertEqual(len(signer.calls), 1)
                self.assertEqual(len(requests), 1)

    def test_api_admin_and_missing_runtime_roles_block_before_signer_or_network(self):
        for role in (None, "", "api", "admin", "worker"):
            with self.subTest(role=role):
                env = {
                    "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
                    "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
                }
                if role is not None:
                    env["NOTEAI_RUNTIME_ROLE"] = role
                signer = FakeSigner()
                client = mock.Mock()
                adapter = xhs.SpiderXHSHTTPAdapter(
                    credentials=credentials(), signer=signer, client=client
                )
                with mock.patch.dict(os.environ, env, clear=True):
                    with self.assertRaisesRegex(xhs.XHSAdapterError, "runtime_role_not_allowed"):
                        adapter.search_recommend("测试")
                self.assertEqual(signer.calls, [])
                client.request.assert_not_called()

    def test_wrong_adapter_fails_before_signing_or_network(self):
        adapter, signer, requests = self.adapter([])
        with mock.patch.dict(os.environ, {"NOTEAI_XHS_ACQUISITION_ADAPTER": "legacy"}):
            with self.assertRaisesRegex(xhs.XHSAdapterError, "adapter_not_selected"):
                adapter.homefeed()
        self.assertEqual(signer.calls, [])
        self.assertEqual(requests, [])

    def test_session_health_is_local_and_secret_free(self):
        health = credentials().public_health()
        rendered = repr(health)
        self.assertEqual(health["status"], "ready")
        self.assertNotIn("SECRET_A1", rendered)
        self.assertNotIn("SECRET_SESSION", rendered)
        self.assertNotIn("cookie_header", health)

    def test_cookie_jar_filters_domain_expiry_and_uses_last_valid_duplicate(self):
        future = 4102444800
        records = [
            {"name": "a1", "value": "OLD_A1", "domain": ".xiaohongshu.com", "expires": future},
            {"name": "a1", "value": "NEW_A1", "domain": "xiaohongshu.com", "expires": future},
            {"name": "web_session", "value": "VALID_SESSION", "domain": ".xiaohongshu.com", "expires": future},
            {"name": "legacy", "value": "BLANK_DOMAIN", "domain": ""},
            {"name": "foreign", "value": "FOREIGN_SECRET", "domain": "example.com", "expires": future},
            {"name": "www_only", "value": "WWW_SECRET", "domain": "www.xiaohongshu.com", "expires": future},
            {"name": "lookalike", "value": "LOOKALIKE_SECRET", "domain": "xiaohongshu.com.evil", "expires": future},
            {"name": "expired", "value": "EXPIRED_SECRET", "domain": ".xiaohongshu.com", "expires": 1},
        ]
        creds = xhs.SessionCredentials.from_records(records)

        self.assertEqual(creds.a1, "NEW_A1")
        self.assertEqual(creds.cookie_count, 3)
        self.assertEqual(creds.public_health()["status"], "ready")
        self.assertIn("a1=NEW_A1", creds.cookie_header)
        self.assertIn("web_session=VALID_SESSION", creds.cookie_header)
        self.assertIn("legacy=BLANK_DOMAIN", creds.cookie_header)
        for secret in ("OLD_A1", "FOREIGN_SECRET", "WWW_SECRET", "LOOKALIKE_SECRET", "EXPIRED_SECRET"):
            self.assertNotIn(secret, creds.cookie_header)

        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"success": True, "data": {"items": []}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        signer = FakeSigner()
        adapter = xhs.SpiderXHSHTTPAdapter(credentials=creds, signer=signer, client=client)
        with mock.patch.object(xhs, "_assert_collection_allowed", return_value=None):
            adapter.search_recommend("测试")
        self.assertEqual(signer.calls[0]["a1"], "NEW_A1")
        for secret in ("OLD_A1", "FOREIGN_SECRET", "WWW_SECRET", "LOOKALIKE_SECRET", "EXPIRED_SECRET"):
            self.assertNotIn(secret, requests[0].headers["cookie"])

    def test_cookie_health_marks_only_matching_expired_auth_as_expired(self):
        creds = xhs.SessionCredentials.from_records([
            {"name": "a1", "value": "A1_ONLY", "domain": ".xiaohongshu.com", "expires": 4102444800},
            {"name": "web_session", "value": "EXPIRED_AUTH", "domain": ".xiaohongshu.com", "expires": 1},
            {"name": "id_token", "value": "FOREIGN_AUTH", "domain": "example.com", "expires": 4102444800},
        ])
        self.assertFalse(creds.auth_cookie_present)
        self.assertTrue(creds.auth_cookie_expired)
        self.assertEqual(creds.public_health()["status"], "login_required")
        self.assertNotIn("EXPIRED_AUTH", creds.cookie_header)
        self.assertNotIn("FOREIGN_AUTH", creds.cookie_header)

    def test_node_signer_uses_minimal_env_and_bounded_secret_free_failures(self):
        signer = xhs.NodeSigner(timeout=0.01)
        secret = "SIGNER_SECRET_A1"
        response = json.dumps({"xs": "x", "xt": "t", "xs_common": "c"}).encode()

        def successful_run(argv, **kwargs):
            self.assertNotIn(secret, repr(argv))
            self.assertEqual(set(kwargs["env"]), {"PATH", "NODE_PATH"})
            self.assertNotIn(secret, repr(kwargs["env"]))
            return mock.Mock(returncode=0, stdout=response)

        with mock.patch.object(xhs.subprocess, "run", side_effect=successful_run):
            self.assertEqual(
                signer.sign(api="/read", data={}, a1=secret, method="POST", needs_rap=False)["xs"],
                "x",
            )

        failures = (
            xhs.subprocess.TimeoutExpired(cmd="node", timeout=0.01),
            mock.Mock(returncode=0, stdout=b"x" * (64 * 1024 + 1)),
        )
        expected = ("signer_unavailable", "signer_failed")
        for side_effect, code in zip(failures, expected):
            with self.subTest(code=code), mock.patch.object(
                xhs.subprocess,
                "run",
                side_effect=side_effect if isinstance(side_effect, BaseException) else None,
                return_value=None if isinstance(side_effect, BaseException) else side_effect,
            ):
                with self.assertRaises(xhs.XHSAdapterError) as raised:
                    signer.sign(api="/read", data={}, a1=secret, method="POST", needs_rap=False)
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn(secret, str(raised.exception))

    def test_signer_assets_match_locked_upstream_hashes(self):
        actual = xhs.verify_pinned_signer_assets()
        self.assertEqual(actual, xhs.PINNED_ASSET_SHA256)
        wrapper = xhs.SIGNER_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("fs.readFileSync(0)", wrapper)
        self.assertNotIn("process.argv[2]", wrapper)
        self.assertNotIn("process.env.a1", wrapper)


class DirectAdapterIntegrationTests(unittest.TestCase):
    def test_scheduler_direct_path_builds_homefeed_search_and_recommend_rows_offline(self):
        class FakeAdapter:
            def homefeed(self, **_kwargs):
                return {"items": [{"note_card": {"display_title": "深圳周末探店攻略合集"}}]}

            def search_recommend(self, keyword):
                return {"data": {"items": [{"keyword": f"{keyword}推荐"}]}}

            def search_notes(self, keyword, **_kwargs):
                return {"items": [{"note_card": {"display_title": f"{keyword}真实体验分享"}}]}

        with mock.patch.dict(os.environ, {
            "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
        }), mock.patch.object(xhs, "SpiderXHSHTTPAdapter", FakeAdapter), mock.patch.object(
            scheduler_a, "SEARCH_SEEDS_PER_CATEGORY", 1
        ):
            result = asyncio.run(scheduler_a.scrape_once_http())

        sources = {row["source"] for row in result}
        self.assertIn("homefeed_phrase", sources)
        self.assertIn("search_phrase", sources)
        self.assertIn("search_recommend", sources)
        self.assertGreater(len(result), 0)

    def test_tracking_note_detail_uses_direct_adapter_and_existing_normalizer(self):
        class FakeAdapter:
            def note_detail(self, url):
                self.url = url
                return {
                    "success": True,
                    "data": {"items": [{"note_card": {
                        "title": "真实标题",
                        "interact_info": {
                            "liked_count": "12",
                            "collected_count": "8",
                            "comments_count": "3",
                        },
                    }}]},
                }

        with mock.patch.object(xhs, "SpiderXHSHTTPAdapter", FakeAdapter):
            result = asyncio.run(crawler._extract_note_data_with_spider_http(
                "https://www.xiaohongshu.com/explore/0123456789abcdef"
            ))

        self.assertEqual(result, {
            "likes": 12,
            "saves": 8,
            "comments": 3,
            "title": "真实标题",
        })

    def test_tracking_lock_defaults_closed_before_database_or_network_work(self):
        for value in (None, "", "unknown", "1"):
            with self.subTest(value=value):
                env = {
                    "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
                    "NOTEAI_RUNTIME_ROLE": "xhs-http",
                }
                if value is not None:
                    env["NOTEAI_XHS_COLLECTION_SUSPENDED"] = value
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
                    crawler,
                    "_due_tracking_notes",
                    side_effect=AssertionError("database must not be read while suspended"),
                ):
                    result = asyncio.run(crawler.run_collection_round())

                self.assertEqual(result, {
                    "skipped": True,
                    "reason": "collection_suspended",
                    "collected": 0,
                })

    def test_tracking_direct_role_gate_stops_before_database_or_network_work(self):
        for role in (None, "", "api", "admin"):
            with self.subTest(role=role):
                env = {
                    "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
                    "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
                }
                if role is not None:
                    env["NOTEAI_RUNTIME_ROLE"] = role
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
                    crawler,
                    "_due_tracking_notes",
                    side_effect=AssertionError("database must not be read for a blocked role"),
                ):
                    result = asyncio.run(crawler.run_collection_round())

                self.assertEqual(result, {
                    "skipped": True,
                    "reason": "runtime_role_not_allowed",
                    "collected": 0,
                })

    def test_tracking_legacy_explicit_suspension_stops_before_database_or_browser(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_RUNTIME_ROLE": "local",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "1",
        }, clear=True), mock.patch.object(
            crawler,
            "_due_tracking_notes",
            side_effect=AssertionError("database/browser route must remain unreachable"),
        ):
            result = asyncio.run(crawler.run_collection_round())

        self.assertEqual(result, {
            "skipped": True,
            "reason": "collection_suspended",
            "collected": 0,
        })

    def test_legacy_route_only_explicit_truthy_values_suspend(self):
        for value in ("1", "true", "yes", "on", " TRUE "):
            with self.subTest(value=value), mock.patch.dict(os.environ, {
                "NOTEAI_RUNTIME_ROLE": "legacy",
                "NOTEAI_XHS_COLLECTION_SUSPENDED": value,
            }, clear=True), mock.patch.object(
                market_timing_worker,
                "scrape_once",
                side_effect=AssertionError("browser scrape must remain unreachable"),
            ) as browser:
                with self.assertRaisesRegex(xhs.XHSAdapterError, "collection_suspended"):
                    asyncio.run(market_timing_worker._scrape_selected_adapter(""))
                browser.assert_not_awaited()

        for value in (None, "0"):
            env = {"NOTEAI_RUNTIME_ROLE": "local"}
            if value is not None:
                env["NOTEAI_XHS_COLLECTION_SUSPENDED"] = value
            with self.subTest(value=value), mock.patch.dict(
                os.environ, env, clear=True
            ), mock.patch.object(
                market_timing_worker, "scrape_once", return_value=["legacy"]
            ) as browser:
                result = asyncio.run(market_timing_worker._scrape_selected_adapter(""))
                self.assertEqual(result, ["legacy"])
                browser.assert_awaited_once_with()

    def test_direct_market_timing_failure_never_falls_back_to_browser(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
        }, clear=True), mock.patch.object(
                market_timing_worker,
                "scrape_once_http",
                side_effect=xhs.XHSAdapterError("challenge"),
            ) as direct, mock.patch.object(
                market_timing_worker,
                "scrape_once",
                side_effect=AssertionError("browser fallback must remain unreachable"),
            ) as browser:
                with self.assertRaisesRegex(xhs.XHSAdapterError, "challenge"):
                    asyncio.run(market_timing_worker._scrape_selected_adapter(xhs.ADAPTER_NAME))

        direct.assert_awaited_once_with()
        browser.assert_not_awaited()

    def test_market_timing_direct_role_gate_never_reaches_direct_or_browser_scrape(self):
        for role in (None, "", "api", "admin"):
            with self.subTest(role=role):
                env = {"NOTEAI_XHS_COLLECTION_SUSPENDED": "0"}
                if role is not None:
                    env["NOTEAI_RUNTIME_ROLE"] = role
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
                    market_timing_worker,
                    "scrape_once_http",
                    side_effect=AssertionError("direct scrape must remain unreachable"),
                ) as direct, mock.patch.object(
                    market_timing_worker,
                    "scrape_once",
                    side_effect=AssertionError("browser scrape must remain unreachable"),
                ) as browser:
                    with self.assertRaisesRegex(xhs.XHSAdapterError, "runtime_role_not_allowed"):
                        asyncio.run(market_timing_worker._scrape_selected_adapter(xhs.ADAPTER_NAME))

                direct.assert_not_awaited()
                browser.assert_not_awaited()

    def test_tracking_challenge_stops_round_after_first_note(self):
        calls = []

        async def fetch_detail(note):
            calls.append(note["id"])
            raise xhs.XHSAdapterError("challenge")

        notes = [
            {"id": "note-1", "status": "pending"},
            {"id": "note-2", "status": "pending"},
        ]
        with mock.patch.object(crawler, "_record_tracking_failure") as failure, \
                mock.patch.object(crawler, "_save_log"):
            result = asyncio.run(crawler._process_tracking_notes(notes, fetch_detail))

        self.assertEqual(calls, ["note-1"])
        self.assertEqual(result, {"collected": 0, "failed": 1, "total": 2})
        failure.assert_called_once_with(notes[0], "challenge", "challenge")


if __name__ == "__main__":
    unittest.main()
