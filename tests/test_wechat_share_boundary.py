"""Offline public-boundary integration; no database or WeChat requests."""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import public_account
import public_product


class WechatShareBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_ACCOUNT_ONLY": "1", "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com,https://www.noteaipro.com",
        })
        self.env.start()
        app = FastAPI()

        @app.post("/wechat/share-config")
        async def sign(request: Request):
            return {"received": await request.json()}

        @app.get("/covers")
        async def covers():
            self.fail("private handler must not run")

        app.add_middleware(public_account.PublicAccountBoundary)
        self.client = TestClient(app, headers={"Origin": "https://noteaipro.com"})

    def tearDown(self):
        self.env.stop()

    def test_only_exact_post_is_anonymous_and_origin_checked(self):
        with mock.patch.object(public_product, "authenticated_user",
                side_effect=AssertionError("share must not access account/session")):
            response = self.client.post("/wechat/share-config", json={"url": "https://noteaipro.com/"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["received"], {"url": "https://noteaipro.com/"})
            self.assertEqual(response.headers["cache-control"], "no-store")
            for path in ["/wechat/share-config/", "/wechat/other", "/wechat%2fshare-config"]:
                self.assertEqual(self.client.post(path, json={}).status_code, 404)
            self.assertEqual(self.client.get("/wechat/share-config").status_code, 404)
            self.assertEqual(self.client.post("/wechat/share-config", json={},
                headers={"Origin": "https://attacker.invalid"}).status_code, 403)
            self.assertEqual(self.client.post("/wechat/share-config", json={},
                headers={"Origin": ""}).status_code, 403)
            self.assertEqual(self.client.post("/wechat/share-config", content="{}").status_code, 415)
            self.assertEqual(self.client.post("/wechat/share-config", content="x" * 8193,
                headers={"Content-Type": "application/json"}).status_code, 413)

    def test_account_only_release_stays_closed(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"}):
            self.assertEqual(self.client.post("/wechat/share-config", json={}).status_code, 404)

    def test_private_routes_still_require_login(self):
        with mock.patch.object(public_product, "authenticated_user",
                side_effect=HTTPException(401, "请先登录")) as authenticate:
            self.assertEqual(self.client.get("/covers").status_code, 401)
            authenticate.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
