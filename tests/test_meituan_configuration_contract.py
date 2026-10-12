"""Offline Meituan CLI configuration/authorization contract; no provider calls."""

import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import fact_enrichment as facts  # noqa: E402


SUCCESS = (
    "[**广州甲酒店**](https://example.invalid/hotel) 美团真实评分4.7 ￥399起/晚\n"
    "酒店地址：广州市天河区甲路1号。"
)
SYNTHETIC_TOKEN = "synthetic-private-token"


class MeituanConfigurationContractTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "NOTEAI_FACT_SEARCH": "1",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
            "MEITUAN_RAW_JSON": "1",
        }, clear=True))
        for name, value in (
            ("_CACHE", {}), ("_LAST_READ", {}),
            ("_meituan_travel_cli_path", "/offline/mock-mttravel"),
            ("_meituan_travel_cli_executable", True),
            ("_meituan_travel_token", SYNTHETIC_TOKEN),
            ("fact_search_enabled", True), ("_cache_ttl_seconds", 60),
            ("_authorized_fact_items", []),
        ):
            if isinstance(value, dict):
                self.stack.enter_context(mock.patch.object(facts, name, value))
            else:
                self.stack.enter_context(mock.patch.object(facts, name, return_value=value))
        self.homes = []
        self.run = self.stack.enter_context(mock.patch.object(facts.subprocess, "run"))

    def read(self):
        return facts.enrich_content_facts("旅行", "广州甲酒店", "广州", provider="meituan_travel")

    def response(self, args, kwargs, *, code=0, output=SUCCESS):
        child = kwargs["env"]
        self.assertNotIn("MEITUAN_RAW_JSON", child)
        self.assertNotIn(SYNTHETIC_TOKEN, " ".join(args))
        home = Path(child["HOME"])
        self.homes.append(home)
        config = home / ".config" / "meituan-travel" / "config.json"
        self.assertEqual(json.loads(config.read_text())["key"], SYNTHETIC_TOKEN)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        return subprocess.CompletedProcess(args, code, stdout=output, stderr="")

    def test_raw_json_setting_cannot_reach_cli(self):
        child = facts._meituan_travel_subprocess_env(Path("/offline/private-home"))
        self.assertNotIn("MEITUAN_RAW_JSON", child)
        self.assertEqual(child["HOME"], "/offline/private-home")
        self.assertEqual(child["NO_COLOR"], "1")

    def test_normal_success_retains_source_facts_and_cleans_private_config(self):
        self.run.side_effect = lambda args, **kw: self.response(args, kw)
        result = self.read()
        self.assertEqual(result["status"], "matched")
        self.assertIn("399", result["facts"]["price"])
        self.assertIn("4.7", result["facts"]["rating"])
        self.assertEqual(result["sources"][0]["source"], "美团酒旅")
        self.assertIn("已提取字段", facts.format_fact_context(result))
        self.assertEqual(self.run.call_count, 1)
        self.assertTrue(all(not home.exists() for home in self.homes))

    def test_authorization_failure_has_no_facts_or_automatic_retry(self):
        self.run.side_effect = lambda args, **kw: self.response(args, kw, code=3, output="")
        result = self.read()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MEITUAN_TRAVEL_AUTH_FAILED")
        self.assertEqual(result["facts"], {})
        self.assertEqual(result["sources"], [])
        self.assertIn("不得编造地址、价格、评分或营业时间", facts.format_fact_context(result))
        self.assertEqual(self.run.call_count, 1)
        self.assertTrue(all(not home.exists() for home in self.homes))

    def test_raw_json_auth_bypass_cannot_be_enabled_by_runtime_configuration(self):
        def pinned_cli_contract(args, **kwargs):
            # Synthetic reproduction of the pinned CLI's raw-mode early return.
            if kwargs["env"].get("MEITUAN_RAW_JSON") == "1":
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
                    "code": 401, "msg": "访问令牌已过期", "data": "",
                }), stderr="")
            return self.response(args, kwargs, code=3, output="")

        self.run.side_effect = pinned_cli_contract
        result = self.read()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MEITUAN_TRAVEL_AUTH_FAILED")
        self.assertEqual(result["facts"], {})
        self.assertEqual(self.run.call_count, 1)

    def test_missing_token_stops_before_cli(self):
        with mock.patch.object(facts, "_meituan_travel_token", return_value=""):
            result = self.read()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MEITUAN_TRAVEL_TOKEN_MISSING")
        self.assertEqual(result["facts"], {})
        self.run.assert_not_called()

    def test_explicit_later_read_recovers_without_caching_authorization_failure(self):
        responses = iter(((3, ""), (0, SUCCESS)))

        def next_response(args, **kwargs):
            code, output = next(responses)
            return self.response(args, kwargs, code=code, output=output)

        self.run.side_effect = next_response
        failed = self.read()
        recovered = self.read()
        self.assertEqual(failed["error_code"], "MEITUAN_TRAVEL_AUTH_FAILED")
        self.assertEqual(recovered["status"], "matched")
        self.assertFalse(recovered["cached"])
        self.assertIn("399", recovered["facts"]["price"])
        self.assertEqual(self.run.call_count, 2)
        self.assertTrue(all(not home.exists() for home in self.homes))


if __name__ == "__main__":
    unittest.main()
