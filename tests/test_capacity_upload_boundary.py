"""The existing upload boundary admits parallel streams within one byte budget.

Only authentication and the downstream dispatcher are replaced. This verifies
ASGI admission/cancellation, not multipart decoding, model throughput or storage.
"""
import asyncio
import os
import unittest
from unittest import mock

from tests.test_public_accounts import public
import public_product


class UploadBoundaryCapacityTests(unittest.TestCase):
    def test_two_uploads_enter_before_finish_but_aggregate_body_never_overbooks(self):
        async def run():
            entered, finish = [], asyncio.Event()
            async def dispatch(app, scope, receive, send, body, **kwargs):
                entered.append(scope["path"])
                await finish.wait()
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

            async def unused(*args):
                raise AssertionError("unexpected outside handler")

            boundary = public.PublicAccountBoundary(unused)
            async def submit(path, declared):
                output = []
                async def receive():
                    return {"type": "http.request", "body": b"", "more_body": False}
                async def send(message):
                    output.append(message)
                await boundary({"type": "http", "method": "POST", "path": path,
                    "raw_path": path.encode(), "headers": [
                        (b"origin", b"https://noteaipro.com"),
                        (b"content-type", b"multipart/form-data; boundary=synthetic"),
                        (b"content-length", str(declared).encode())]}, receive, send)
                return output

            with mock.patch.object(public_product, "dispatch", side_effect=dispatch):
                first = asyncio.create_task(submit("/upload-video", 90 * 1024 * 1024))
                second = asyncio.create_task(submit("/upload-image", 8 * 1024 * 1024))
                try:
                    for _ in range(100):
                        if len(entered) == 2:
                            break
                        await asyncio.sleep(.001)
                    self.assertEqual(entered, ["/upload-video", "/upload-image"])
                    self.assertEqual(boundary.media_json_bytes, 98 * 1024 * 1024)
                    rejected = await submit("/upload-video", 40 * 1024 * 1024)
                    self.assertEqual(rejected[0]["status"], 429)
                    self.assertEqual(len(entered), 2)
                    self.assertLessEqual(boundary.media_json_bytes, boundary.media_json_budget)
                finally:
                    finish.set()
                    results = await asyncio.gather(first, second)
                self.assertEqual([result[0]["status"] for result in results], [200, 200])
                self.assertEqual(boundary.media_json_bytes, 0)

        with mock.patch.dict(os.environ, {
                "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_UPLOAD_STREAM_CONCURRENCY": "2",
                "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com"}), \
             mock.patch.object(public, "enabled", return_value=True), \
             mock.patch.object(public, "product_enabled", return_value=True), \
             mock.patch.object(public_product, "image_enabled", return_value=True), \
             mock.patch.object(public_product, "video_enabled", return_value=True), \
             mock.patch.object(public_product, "media_enabled", return_value=True), \
             mock.patch.object(public_product, "authenticated_user", return_value={"id": "synthetic"}):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
