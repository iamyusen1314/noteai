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
        self.assertIn("入住15:00以后", extracted["hours"])
        self.assertIn("早餐07:00-10:00", extracted["hours"])
        self.assertIn("儿童乐园", extracted["review_keywords"])
        self.assertIn("童趣乐园门票", extracted["deal"])
        self.assertIn("以美团实时页为准", extracted["deal"])
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
