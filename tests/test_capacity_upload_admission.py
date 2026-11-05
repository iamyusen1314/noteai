"""Local upload saturation must not block the original SSE heartbeat.

The normal upload, private SQLite references and in-memory object backend run.
Only the first image decode is held; no supplier HTTP or production data runs.
"""
import asyncio
import io
import json
import os
import socket
import threading
import unittest
from unittest import mock

from PIL import Image
from starlette.datastructures import Headers, UploadFile

from tests.test_generation_multiuser_admission import api, admission, db, public


class CapacityUploadAdmissionTests(unittest.TestCase):
    def test_saturated_upload_decode_keeps_sse_live_and_original_storage_contract(self):
        from tests.test_private_storage_recovery import PrivateStorageRecoveryContractTests
        fixture = PrivateStorageRecoveryContractTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        users = ("capacity-upload-first", "capacity-upload-second", "capacity-upload-queue-full")
        for user in users:
            fixture.create_user(user)
        original = io.BytesIO()
        Image.new("RGBA", (300, 200), (255, 0, 0, 128)).save(original, "PNG")
        raw = original.getvalue()
        # This is the original published JPEG contract, evaluated before the
        # controlled blocking image wrapper is installed.
        with Image.open(io.BytesIO(raw)) as source:
            expected = io.BytesIO()
            source.convert("RGB").save(expected, "JPEG", quality=90, optimize=True, progressive=False)
        expected_bytes = expected.getvalue()
        manager = admission.Admission(admission.Limits(media_workers=1, pending_calls=1))
        original_open = Image.open
        first_load_entered, release_decode, heartbeat = (threading.Event() for _ in range(3))
        decode_threads, decode_order, heartbeat_during_decode = [], [], []
        decode_lock = threading.Lock()
        loop_thread = threading.get_ident()

        class HeldImage:
            def __init__(self, image):
                self.image = image

            def __getattr__(self, name):
                return getattr(self.image, name)

            def __enter__(self):
                self.image.__enter__()
                return self

            def __exit__(self, *args):
                return self.image.__exit__(*args)

            def load(self):
                with decode_lock:
                    ordinal = len(decode_order)
                    decode_order.append(self.image.filename)
                    decode_threads.append(threading.get_ident())
                if ordinal == 0:
                    first_load_entered.set()
                    responsive = heartbeat.wait(1)
                    heartbeat_during_decode.append(responsive)
                    # The old async endpoint cannot deliver its concurrent
                    # heartbeat while blocked here, so release that red case.
                    if responsive and not release_decode.wait(3):
                        raise AssertionError("Controlled image decode was not released")
                return self.image.load()

        def held_open(*args, **kwargs):
            return HeldImage(original_open(*args, **kwargs))

        async def scenario():
            stop_sse = asyncio.Event()
            async def source():
                await stop_sse.wait()
                if False:
                    yield ""

            async def observe_heartbeat():
                stream = api._timed_sse_stream(source(), operation="generate", success_types={"complete"})
                try:
                    async for chunk in stream:
                        event = json.loads(chunk.removeprefix("data: ").strip())
                        if event["type"] == "heartbeat":
                            heartbeat.set()
                            return
                finally:
                    await stream.aclose()

            async def upload(user):
                invocation = public.Invocation(user, "synthetic-upload-" + user, route="/upload-image")
                marker = public._invocation.set(invocation)
                try:
                    file = UploadFile(file=io.BytesIO(raw), filename="private.png",
                        headers=Headers({"content-type": "image/png"}))
                    return await api.upload_image(file, {"id": user}, [])
                finally:
                    public._invocation.reset(marker)

            watcher = asyncio.create_task(observe_heartbeat())
            jobs = [asyncio.create_task(upload(user)) for user in users[:2]]
            try:
                await asyncio.sleep(.05)
                self.assertTrue(first_load_entered.is_set())
                self.assertEqual(heartbeat_during_decode, [True],
                    "A normal image decode blocked the original SSE heartbeat")
                self.assertNotEqual(decode_threads[0], loop_thread)
                self.assertEqual(len(decode_order), 1,
                    "A second upload bypassed the saturated original media slot")
                with manager.media.lock:
                    self.assertEqual(len(manager.media.active), 1)
                    self.assertEqual(len(manager.media._tickets()), 1)
                with self.assertRaises(api.HTTPException) as full:
                    await upload(users[2])
                self.assertEqual(full.exception.status_code, 429)
                self.assertEqual(full.exception.detail["code"], "IMAGE_UPLOAD_CAPACITY_BUSY")
                self.assertEqual(len(decode_order), 1)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM private_media_refs")[0], 0)
                release_decode.set()
                results = await asyncio.gather(*jobs)
                await watcher
                self.assertEqual(len(decode_order), 2)
                self.assertTrue(all(thread != loop_thread for thread in decode_threads))
                for user, result in zip(users[:2], results):
                    reference, body = api._private_storage.load_media_bytes(result["media_ref"], user_id=user, purpose="image")
                    self.assertEqual(body, expected_bytes)
                    self.assertEqual((result["width"], result["height"], result["stored_size"]), (300, 200, len(body)))
                    self.assertEqual(reference.content_type, "image/jpeg")
                with manager.media.lock:
                    self.assertEqual(manager.media.active, {})
                    self.assertEqual(manager.media._tickets(), [])
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM usage_records")[0], 0)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
                self.assertEqual([db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user,))[0]
                                 for user in users], [1000, 1000, 1000])
            finally:
                release_decode.set()
                await asyncio.gather(*jobs, return_exceptions=True)
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1"}), \
             mock.patch.object(admission, "_instance", manager), \
             mock.patch.object(Image, "open", side_effect=held_open), \
             mock.patch.object(api, "_SSE_HEARTBEAT_SECONDS", .01), \
             mock.patch.object(socket.socket, "connect", side_effect=AssertionError("No external socket allowed")), \
             mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No external socket allowed")):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
