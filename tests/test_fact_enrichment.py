import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import fact_enrichment as facts  # noqa: E402


class FactEnrichmentTests(unittest.TestCase):
    def test_hotel_package_hours_address_and_business_source_keep_their_scope(self):
        answer = ('![酒店图片](https://images.example.invalid/photo.jpg)\n'
            '[**广州长隆酒店**](http://dpurl.cn/hotel-test) 美团豪华型 **美团真实评分4.7** **￥929起/晚** 亲子酒店\n'
            '**酒店地址**：番禺区长隆/南村汉溪大道东299号\n'
            '**营业时间**：9:30-18:30（公主变装套餐预约时间）\n'
            '**价格区间**：998元起（狩猎大床房/双床房套餐），具体价格会根据房型和包含的门票套餐有所不同。')
        item = facts._meituan_travel_items(answer)[0]
        result = facts.extract_facts_from_search_items([item])
        self.assertEqual(item['url'], 'http://dpurl.cn/hotel-test')
        self.assertEqual(result['address'], '番禺区长隆/南村汉溪大道东299号')
        self.assertNotIn('hours', result)
        self.assertIn('公主变装套餐预约时间', result['booking'])
        self.assertIn('￥929起/晚', result['price'])
        self.assertIn('998元起（狩猎大床房/双床房套餐）', result['deal'])

    def test_hotel_negative_facilities_and_late_qualifiers_are_not_invented(self):
        answer = ('广州长隆酒店 美团真实评分4.7 ￥929起/晚。\n'
            '不提供免费穿梭巴士，套餐不含无限次入园。\n'
            '办理入住须在15:00以前，退房可在11:00以后。\n'
            + '补充说明。' * 500 + '\n酒店地址：广州市番禺区汉溪大道东299号\n'
            '[广州长隆酒店](https://example.invalid/hotel)')
        item = facts._meituan_travel_items(answer)[0]
        result = facts.extract_facts_from_search_items([item])
        self.assertIn('不提供免费穿梭巴士', result['review_keywords'])
        self.assertIn('不含无限次入园', result['deal'])
        self.assertNotIn('可能包含', result['deal'])
        self.assertIn('15:00以前', result['hours'])
        self.assertIn('11:00以后', result['hours'])
        self.assertIn('汉溪大道东299号', result['address'])
        self.assertEqual(item['url'], 'https://example.invalid/hotel')

    def test_named_hotel_mismatch_is_not_matched_or_injected(self):
        with mock.patch.object(facts,'fact_search_enabled',return_value=True), \
             mock.patch.object(facts,'_authorized_fact_items',return_value=[]), \
             mock.patch.object(facts,'_cache_ttl_seconds',return_value=0), \
             mock.patch.object(facts,'_search',return_value=('meituan_travel',[
                 {'title':'上海其他酒店','source':'美团酒旅','facts':{'price':'￥499起/晚'}}])):
            result=facts.enrich_content_facts('旅行','广州长隆酒店','广州',provider='meituan_travel')
        self.assertEqual(result['error_code'],'MERCHANT_OBJECT_MISMATCH')
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['facts'])
        self.assertNotIn('￥499', facts.format_fact_context(result))

    def test_hotel_card_qualifier_and_selected_source_are_preserved(self):
        qualifier='套餐说明' * 75 + '不包含门票且不可退订'
        item=facts._meituan_travel_items('[**广州长隆酒店**](https://example.invalid/target) 美团真实评分4.7 ￥929起/晚 '+qualifier)[0]
        self.assertIn(qualifier, facts.extract_facts_from_search_items([item])['deal'])
        others=[{'title':name,'source':'美团酒旅','url':'https://example.invalid/'+str(i),'facts':{'price':'￥499起/晚'}}
                for i,name in enumerate(['广州甲酒店','广州乙酒店','广州丙酒店'])]
        with mock.patch.object(facts,'fact_search_enabled',return_value=True), \
             mock.patch.object(facts,'_authorized_fact_items',return_value=[]), \
             mock.patch.object(facts,'_cache_ttl_seconds',return_value=0), \
             mock.patch.object(facts,'_search',return_value=('meituan_travel',others+[item])):
            result=facts.enrich_content_facts('旅行','广州长隆酒店','广州',provider='meituan_travel')
        self.assertEqual([s['url'] for s in result['sources']],['https://example.invalid/target'])
        self.assertEqual([e['name'] for e in result['entities']],['广州长隆酒店'])

    def test_distinct_poi_fields_never_form_one_merchant(self):
        items=[{'title':'甲店','facts':{'address':'甲路1号'}},
               {'title':'乙店','facts':{'price':'人均88元','hours':'09:00-18:00'}}]
        result=facts.extract_facts_from_search_items(items)
        self.assertEqual(result,{'address':'甲路1号'})

    def test_brand_and_branch_survive_full_query_path(self):
        query=facts.build_fact_query('美食','长禧家.珑厨(万博广晟店)探店','广州番禺粤菜')
        keyword=facts._amap_keyword_from_query(query)
        self.assertEqual(keyword,'长禧家.珑厨(万博广晟店)')
        self.assertTrue(facts._amap_poi_matches_keyword({'name':keyword},keyword))
        for name in ['别家粤菜(万博广晟店)','长禧家.珑厨(东风店)']:
            self.assertFalse(facts._amap_poi_matches_keyword({'name':name,'address':keyword},keyword))

    def test_amap_branch_match_keeps_brand_separate_from_business_descriptor(self):
        keyword = '广州陶陶居(正佳广场店)'
        for name in ('陶陶居(正佳广场店)', '陶陶居酒家(正佳广场店)',
                     '广州陶陶居酒家（正佳广场店）'):
            with self.subTest(name=name):
                self.assertTrue(facts._amap_poi_matches_keyword({'name': name}, keyword))
        for name in ('别家酒家(正佳广场店)', '陶陶居酒家(东风店)',
                     '陶陶居酒家(新正佳广场店)', '陶陶居酒家(正佳广场店二店)',
                     '北京陶陶居酒家(正佳广场店)', '假陶陶居酒家(正佳广场店)',
                     '正佳广场(陶陶居酒家店)'):
            with self.subTest(name=name):
                self.assertFalse(facts._amap_poi_matches_keyword(
                    {'name': name, 'address': keyword}, keyword))

    def _amap_mock_result(self, pois, detail=None):
        """Provider-shaped fixtures; no real HTTP, quota DB or model calls."""
        import httpx
        calls = []
        def respond(request):
            calls.append((request.url.path, dict(request.url.params)))
            rows = pois if request.url.path == '/v3/place/text' else [detail]
            return httpx.Response(200, json={'status': '1', 'infocode': '10000', 'pois': rows})
        real_client = httpx.Client
        with mock.patch.dict(os.environ, {'AMAP_WEB_KEY': 'fixture-not-a-secret', 'NOTEAI_FACT_SEARCH': '1'}), \
             mock.patch.object(facts, '_authorized_fact_items', return_value=[]), \
             mock.patch.object(facts, '_cache_ttl_seconds', return_value=0), \
             mock.patch.object(facts.amap_quota, 'admit', side_effect=lambda endpoint: endpoint) as admit, \
             mock.patch.object(facts.amap_quota, 'finish') as finish, \
             mock.patch.object(facts.httpx, 'Client', side_effect=lambda **kw: real_client(
                 transport=httpx.MockTransport(respond), **kw)):
            result = facts.enrich_content_facts('美食', '广州陶陶居(正佳广场店)',
                '门店名：广州陶陶居(正佳广场店)\n只核对本分店公开事实', provider='amap')
        self.assertEqual(admit.call_count, len(calls))
        self.assertEqual(finish.call_count, len(calls))
        return result, calls

    def test_amap_branch_http_query_has_no_fact_suffix_and_same_poi_detail(self):
        result, calls = self._amap_mock_result(
            [{'id': 'fixture-A', 'name': '陶陶居酒家(正佳广场店)', 'address': '广州市测试地址'}],
            {'id': 'fixture-A', 'business': {'cost': '88'}})
        self.assertEqual([path for path, _ in calls], ['/v3/place/text', '/v5/place/detail'])
        self.assertEqual(calls[0][1]['keywords'], '广州陶陶居(正佳广场店)')
        self.assertEqual(calls[0][1]['city'], '广州')
        self.assertEqual(calls[0][1]['citylimit'], 'true')
        self.assertEqual(calls[1][1]['id'], 'fixture-A')
        self.assertEqual(result['status'], 'matched')
        self.assertFalse(result['cached'])
        self.assertEqual(result['calls']['http_requests'], 2)
        self.assertIn('88', result['facts']['price'])
        self.assertEqual(result['sources'][0]['url'], 'amap://poi/fixture-A')

    def test_amap_branch_multiple_ids_remain_ambiguous_without_detail(self):
        result, calls = self._amap_mock_result([
            {'id': 'fixture-A', 'name': '陶陶居(正佳广场店)', 'address': '甲地址'},
            {'id': 'fixture-B', 'name': '陶陶居酒家(正佳广场店)', 'address': '乙地址'}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['error_code'], 'MERCHANT_SELECTION_REQUIRED')
        self.assertFalse(result['facts'])
        self.assertFalse(result['entities'])

    def test_amap_empty_or_other_branch_is_not_claimed_as_a_match(self):
        for pois in ([], [{'id': 'fixture-other', 'name': '陶陶居酒家(东风店)',
                           'address': '广州陶陶居(正佳广场店)'}]):
            with self.subTest(pois=pois):
                result, calls = self._amap_mock_result(pois)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result['status'], 'no_matching_facts')
                self.assertFalse(result['facts'])
                self.assertFalse(result['sources'])

    def test_amap_branch_wrong_detail_id_cannot_supply_facts(self):
        result, calls = self._amap_mock_result(
            [{'id': 'fixture-A', 'name': '陶陶居酒家(正佳广场店)', 'address': '甲地址'}],
            {'id': 'fixture-B', 'business': {'cost': '88'}})
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['error_code'], 'AMAP_DETAIL_ID_MISMATCH')
        self.assertFalse(result['facts'])
        self.assertFalse(result['sources'])

    def test_hotel_bullets_keep_names_and_do_not_cross_fill(self):
        items=facts._meituan_travel_items('- **广州甲酒店**：￥399起/晚。\n- **广州乙酒店**：\n酒店地址：广州市天河区乙路2号。')
        self.assertEqual([item['title'] for item in items],['广州甲酒店','广州乙酒店'])
        self.assertIn('399',items[0]['facts']['price'])
        self.assertNotIn('address',items[0]['facts'])
        self.assertIn('乙路2号',items[1]['facts']['address'])
        self.assertNotIn('price',items[1]['facts'])
        self.assertNotIn('price',facts._extract_meituan_travel_facts('广州甲酒店 ￥XX起/晚'))

    def test_local_facts_preserve_provider_failure_as_partial(self):
        local={'title':'测试店','url':'https://example.invalid/verified','source':'local_verified','facts':{'address':'广州市甲路1号'}}
        with mock.patch.object(facts,'fact_search_enabled',return_value=True), \
             mock.patch.object(facts,'_authorized_fact_items',return_value=[local]), \
             mock.patch.object(facts,'_cache_ttl_seconds',return_value=0), \
             mock.patch.object(facts,'_search',side_effect=facts.FactProviderError('AMAP_BUSINESS_10003')):
            result=facts.enrich_content_facts('美食','测试店','',provider='amap')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['facts']['address'],'广州市甲路1号')
        self.assertEqual(result['calls']['partial_errors'],['AMAP_BUSINESS_10003'])
        self.assertEqual(facts._LAST_READ['amap']['status'],'partial')

    def test_plain_hotel_lines_keep_entities_separate(self):
        items=facts._meituan_travel_items('广州甲酒店，￥399起/晚。\n广州乙酒店，酒店地址：广州市天河区乙路2号。')
        self.assertEqual(len(items),2)
        self.assertNotIn('address',items[0]['facts'])
        self.assertNotIn('price',items[1]['facts'])
        inline=facts._meituan_travel_items('广州甲酒店，￥399起/晚；广州乙酒店，酒店地址：广州市天河区乙路2号。')
        self.assertEqual(len(inline),2)
        self.assertNotIn('address',inline[0]['facts'])
        self.assertNotIn('price',inline[1]['facts'])

    def test_hotel_introduction_and_pronoun_are_not_extra_merchants(self):
        items=facts._meituan_travel_items('为你找到了广州长隆附近的亲子酒店。\n[**时光公寓**](https://example.invalid/1) 美团真实评分4.8 ￥380起/晚\n这家公寓有亲子房和大滑梯。\n[**瑾程酒店**](https://example.invalid/2) 美团真实评分5.0 ￥326起/晚')
        self.assertEqual([item['title'] for item in items],['时光公寓','瑾程酒店'])
        self.assertIn('大滑梯',items[0]['snippet'])

    def test_cached_partial_keeps_warning_and_observation_with_zero_new_calls(self):
        local={'title':'缓存测试店','source':'local_verified','facts':{'address':'广州市甲路1号'}}
        with mock.patch.object(facts,'_CACHE',{}), mock.patch.object(facts,'fact_search_enabled',return_value=True), \
             mock.patch.object(facts,'_authorized_fact_items',return_value=[local]), \
             mock.patch.object(facts,'_cache_ttl_seconds',return_value=60), \
             mock.patch.object(facts,'_search',side_effect=facts.FactProviderError('AMAP_BUSINESS_10003')) as search:
            first=facts.enrich_content_facts('美食','缓存测试店','',provider='amap')
            cached=facts.enrich_content_facts('美食','缓存测试店','',provider='amap')
        self.assertEqual(search.call_count,1)
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['status'],'partial')
        self.assertEqual(cached['observed_at'],first['observed_at'])
        self.assertEqual(cached['calls']['http_requests'],0)
        self.assertIn('部分供应商数据未取得',facts.format_fact_context(cached))

    def test_amap_business_failure_and_wrong_detail_identity_are_not_empty_success(self):
        import httpx
        with self.assertRaisesRegex(facts.FactProviderError,'AMAP_BUSINESS_10003'):
            facts._amap_response(httpx.Response(200,json={'status':'0','infocode':'10003','info':'synthetic'}))
        with self.assertRaisesRegex(facts.FactProviderError,'AMAP_INVALID_RESPONSE'):
            facts._amap_response(httpx.Response(200,json={'pois':[]}))
        with self.assertRaisesRegex(facts.FactProviderError,'AMAP_DETAIL_ID_MISMATCH'):
            facts._merge_amap_detail({'id':'A','name':'甲店'},{'id':'B','business':{'cost':'88'}})

    def test_runtime_supplier_refresh_has_no_external_calls_and_unknown_history(self):
        with mock.patch.object(facts,'_LAST_READ',{}), \
             mock.patch.object(facts,'_meituan_travel_token',return_value=''), \
             mock.patch.object(facts.httpx.Client,'get',side_effect=AssertionError('no probe')), \
             mock.patch.object(facts.subprocess,'run',side_effect=AssertionError('no CLI')):
            rows=facts.runtime_services()
        self.assertTrue({'amap','meituan_travel'}.issubset({row['id'] for row in rows}))
        self.assertTrue(all(row['latest'] is None for row in rows))
        self.assertTrue(all(row['upstream_probed'] is False for row in rows))

    def test_meituan_runtime_readiness_uses_fixed_missing_codes(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_FACT_SEARCH": "1",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
            "NOTEAI_CLOUD_RUNTIME": "1",
            "MEITUAN_AI_HUB_TOKEN": "",
            "MEITUAN_OPEN_TOKEN": "",
        }), mock.patch.object(facts, "_meituan_travel_config_token", return_value=""):
            with mock.patch.object(facts, "_meituan_travel_cli_path", return_value="/missing/mttravel"):
                missing_cli = facts.meituan_travel_runtime_status()
            self.assertFalse(missing_cli["ok"])
            self.assertTrue(missing_cli["required"])
            self.assertEqual(missing_cli["status_code"], "MEITUAN_TRAVEL_CLI_MISSING")

            with tempfile.TemporaryDirectory() as tmp:
                executable = Path(tmp) / "mttravel"
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o700)
                with mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)):
                    missing_token = facts.meituan_travel_runtime_status()
            self.assertFalse(missing_token["ok"])
            self.assertEqual(missing_token["status_code"], "MEITUAN_TRAVEL_TOKEN_MISSING")

    def test_meituan_runtime_config_accepts_authorization_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"Authorization": "config-value"}), encoding="utf-8")
            self.assertEqual(facts._meituan_travel_config_token(config_path), "config-value")

    def test_meituan_cli_uses_private_temporary_config_and_cleans_it(self):
        observed: dict = {}
        credential = "runtime-value-for-test"

        def fake_run(args, **kwargs):
            observed["args"] = list(args)
            observed["env"] = dict(kwargs["env"])
            observed["home"] = kwargs["env"]["HOME"]
            config_path = Path(observed["home"]) / ".config" / "meituan-travel" / "config.json"
            observed["home_mode"] = stat.S_IMODE(Path(observed["home"]).stat().st_mode)
            observed["config_mode"] = stat.S_IMODE(config_path.stat().st_mode)
            observed["config"] = json.loads(config_path.read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="广州长隆酒店 美团真实评分4.8 ￥929起/晚",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "mttravel"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch.dict(os.environ, {
                "MEITUAN_AI_HUB_TOKEN": credential,
                "MEITUAN_OPEN_TOKEN": "",
            }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)), mock.patch.object(
                facts.subprocess,
                "run",
                side_effect=fake_run,
            ) as run_mock:
                items = facts._search_meituan_travel("广州长隆酒店价格")

        self.assertEqual(len(items), 1)
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(observed["home_mode"], 0o700)
        self.assertEqual(observed["config_mode"], 0o600)
        self.assertEqual(observed["config"], {"key": credential})
        self.assertNotIn(credential, observed["args"])
        self.assertNotIn("MEITUAN_AI_HUB_TOKEN", observed["env"])
        self.assertNotIn("MEITUAN_OPEN_TOKEN", observed["env"])
        self.assertFalse(Path(observed["home"]).exists())

    def test_complete_provider_answer_is_separate_from_noncontent_call_metadata(self):
        answer='广州甲酒店 ￥4XX起/晚。\n' + '完整供应商说明。'*200 + '\n最后一段必须保留。'
        def search(query,provider):
            facts._READ_TRACE.get()['provider_response']=answer
            return provider,facts._meituan_travel_items(answer)
        with mock.patch.object(facts,'fact_search_enabled',return_value=True), \
             mock.patch.object(facts,'_authorized_fact_items',return_value=[]), \
             mock.patch.object(facts,'_cache_ttl_seconds',return_value=0), \
             mock.patch.object(facts,'_search',side_effect=search):
            result=facts.enrich_content_facts('旅行','广州甲酒店','',provider='meituan_travel')
        self.assertEqual(result['provider_response'],answer)
        self.assertNotIn('provider_response',result['calls'])
        self.assertNotIn('price',result['facts'])

    def test_meituan_cli_redacts_token_and_cleans_config_after_failure(self):
        observed: dict = {}
        credential = "sensitive-runtime-value"
        submitted_query = "广州酒店内部查询词"
        response_url = "https://private.example.invalid/result"
        response_body = "third-party diagnostic response"

        def fake_run(args, **kwargs):
            observed["args"] = list(args)
            observed["home"] = kwargs["env"]["HOME"]
            return subprocess.CompletedProcess(
                args,
                2,
                stdout=f"{response_url} {response_body}",
                stderr=f"request failed: {credential} query={submitted_query}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "mttravel"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch.dict(os.environ, {
                "MEITUAN_AI_HUB_TOKEN": credential,
                "MEITUAN_OPEN_TOKEN": "",
            }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)), mock.patch.object(
                facts.subprocess,
                "run",
                side_effect=fake_run,
            ):
                with self.assertRaises(RuntimeError) as raised:
                    facts._search_meituan_travel(submitted_query)

        self.assertEqual(str(raised.exception), "MEITUAN_TRAVEL_EXEC_FAILED")
        self.assertNotIn(credential, str(raised.exception))
        self.assertNotIn(submitted_query, str(raised.exception))
        self.assertNotIn(response_url, str(raised.exception))
        self.assertNotIn(response_body, str(raised.exception))
        self.assertNotIn(credential, observed["args"])
        self.assertFalse(Path(observed["home"]).exists())

    def test_meituan_cli_cleans_config_after_timeout(self):
        observed: dict = {}

        def fake_run(args, **kwargs):
            observed["home"] = kwargs["env"]["HOME"]
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "mttravel"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch.dict(os.environ, {
                "MEITUAN_AI_HUB_TOKEN": "timeout-runtime-value",
                "MEITUAN_OPEN_TOKEN": "",
            }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)), mock.patch.object(
                facts.subprocess,
                "run",
                side_effect=fake_run,
            ):
                with self.assertRaisesRegex(RuntimeError, "^MEITUAN_TRAVEL_TIMEOUT$"):
                    facts._search_meituan_travel("广州酒店")

        self.assertFalse(Path(observed["home"]).exists())

    def test_meituan_travel_output_extracts_structured_hotel_facts(self):
        output = """
为你找到了广州长隆附近的亲子酒店，不过关于交通便利度，有的酒店信息不明确，我会说明清楚。
[**时光公寓\\(广州汉溪长隆地铁站店\\)**](http://dpurl.cn/fiWRYszz) 美团经济型 **美团真实评分4.8** 2018/01开业 **￥380起/晚** 住就送·47元券包 影音酒店 停车场 拍照出片 亲子酒店
这家公寓有龙猫主题大滑梯亲子房，距离汉溪长隆地铁站不远，去长隆也很方便。
[**瑾程酒店\\(广州番禺长隆万博地铁站店\\)**](http://dpurl.cn/8LgdphOz) 美团高档型 **美团真实评分5.0** 2024/01 **￥326起/晚** 住就送·37元券包 会议室 叫醒服务 有影音房 亲子酒店
它靠近南村万博地铁站，交通也很便利。
"""
        extracted = facts._extract_meituan_travel_facts(output)
        self.assertIn("时光公寓", extracted["rating"])
        self.assertIn("美团真实评分4.8", extracted["rating"])
        self.assertIn("￥380起/晚", extracted["price"])
        self.assertIn("亲子酒店", extracted["deal"])
        self.assertIn("汉溪长隆地铁站", extracted["review_keywords"])
        self.assertEqual(extracted["category"], "美团酒旅酒店推荐")

        merged = facts.extract_facts_from_search_items([{
            "title": "美团酒旅事实",
            "snippet": output,
            "facts": extracted,
        }])
        self.assertNotIn("地址和时间这些关键信息", merged.get("address", ""))
        self.assertIn("美团真实评分4.8", merged["rating"])
        self.assertIn("￥380起/晚", merged["price"])

    def test_structured_facts_win_over_regex_fallback_noise(self):
        item = {
            "title": "![酒店图片](http://example.test/img.jpg",
            "snippet": (
                "![酒店图片](http://example.test/img.jpg) "
                "[**广州长隆酒店**](http://dpurl.cn/z71Tvt7z) 美团豪华型 "
                "**美团真实评分4.8** 2018/01装修 **￥929起/晚** "
                "商务出行 叫醒服务 会议室 儿童乐园 拍照出片 "
                "我来帮你把价格、地址和时间摸清楚。地址和时间这些关键信息以平台实时页为准。"
            ),
            "source": "美团酒旅",
            "facts": {
                "rating": "广州长隆酒店美团真实评分4.8",
                "price": "广州长隆酒店￥929起/晚",
                "deal": "广州长隆酒店：商务出行 叫醒服务 会议室 儿童乐园 拍照出片",
                "business_area": "广州长隆",
                "category": "美团酒旅酒店推荐",
            },
        }

        merged = facts.extract_facts_from_search_items([item])
        self.assertEqual(merged["price"], "广州长隆酒店￥929起/晚")
        self.assertEqual(merged["deal"], "广州长隆酒店：商务出行 叫醒服务 会议室 儿童乐园 拍照出片")
        self.assertNotIn("address", merged)
        self.assertNotIn("地址和时间这些关键信息", " ".join(merged.values()))

    def test_meituan_travel_narrative_answer_extracts_core_hotel_facts(self):
        output = """
小团来啦！广州长隆酒店确实是带娃去长隆玩的首选。
广州长隆酒店 美团真实评分4.8 ￥929起/晚。
酒店地址：广州市番禺区汉溪大道东299号，就在长隆度假区的核心位置，免费穿梭巴士可以坐。
酒店办理入住是15:00以后，退房是11:00以前。早餐07:00至10:00开放。
        亲子体验包括儿童乐园、探趣亲子房、白虎自助餐厅和提前半小时入园。
很多套餐包含童趣乐园门票、水上乐园门票和多园畅玩门票。
套餐浮动，价格会随日期变化，我来帮你查当天价格。
"""
        extracted = facts._extract_meituan_travel_facts(output)
        self.assertEqual(extracted["rating"], "广州长隆酒店美团真实评分4.8")
        self.assertEqual(extracted["price"], "广州长隆酒店￥929起/晚")
        self.assertIn("汉溪大道东299号", extracted["address"])
        self.assertIn("入住是15:00以后", extracted["hours"])
        self.assertIn("早餐07:00-10:00", extracted["hours"])
        self.assertIn("儿童乐园", extracted["review_keywords"])
        self.assertIn("童趣乐园门票", extracted["deal"])
        self.assertIn("很多套餐包含", extracted["deal"])
        self.assertNotIn("套餐浮动", " ".join(extracted.values()))

    def test_hotel_name_cleanup_removes_skill_preface(self):
        self.assertEqual(
            facts._clean_hotel_name("我来给你详细说说广州长隆酒店"),
            "广州长隆酒店",
        )

    def test_generic_address_regex_rejects_explanatory_travel_sentence(self):
        merged = facts.extract_facts_from_search_items([{
            "title": "美团酒旅事实",
            "snippet": "关于交通便利度，有的酒店地址和时间这些关键信息不明确，我会说明清楚。",
        }])
        self.assertNotIn("address", merged)


if __name__ == "__main__":
    unittest.main()
