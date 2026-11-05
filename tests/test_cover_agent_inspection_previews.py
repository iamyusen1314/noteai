"""Actual SDK inspection previews; synthetic photos and normal local accounting."""
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image, ImageDraw

from tests import test_cover_agent_progress_feedback as fixtures

runtime, provider = fixtures.runtime, fixtures.provider


def model_reply(turn, calls=None, text="Synthetic technical fixture."):
    message = {"role": "assistant", "content": text,
        "encrypted_content": "TEST_OPAQUE_INSPECTION_" + str(turn)}
    if calls:
        message["tool_calls"] = [{"id": "inspection_" + str(turn) + "_" + str(index),
            "type": "function", "function": {"name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False)}}
            for index, (name, arguments) in enumerate(calls)]
    return {"id": "chatcmpl-inspection-" + str(turn), "object": "chat.completion",
        "created": 1, "model": provider.MODEL, "choices": [{"index": 0,
            "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 20},
            "completion_tokens_details": {"reasoning_tokens": 15}}}


def synthetic_nine():
    """Nine distinct noisy PNGs exceed the SDK's old rolling image budget."""
    image = Image.frombytes("RGB", (1000, 900), random.Random(20261105).randbytes(2700000))
    sources = []
    try:
        for index in range(9):
            copy = image.copy()
            ImageDraw.Draw(copy).rectangle((10, 10, 130, 130),
                fill=(index * 27, 210 - index * 19, 30 + index * 21))
            buffer = io.BytesIO()
            copy.save(buffer, "PNG")
            copy.close()
            payload = buffer.getvalue()
            sources.append({"media_ref": "synthetic-original-" + str(index),
                "payload": payload, "sha256": hashlib.sha256(payload).hexdigest()})
    finally:
        image.close()
    return sources


def price_fixture(original):
    def price(source, model, *, prompt_tokens=0):
        if source == "doubao" and model == provider.MODEL:
            return {"currency": "RMB", "usd_cny": 7.0, "pricing_status": "exact",
                "price_version": provider.PRICE_VERSION, "cache_write_5m": None,
                "cache_write_1h": None, **provider.pricing(prompt_tokens)}
        return original(source, model, prompt_tokens=prompt_tokens)
    return price


class InspectionPreviewSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit approved existing SDK and Node required")

    def test_actual_sdk_first_request_has_nine_trusted_previews_and_known_coverage(self):
        scope = fixtures.budget_fixture.CoverVerificationBudgetTests()
        scope.setUp()
        self.addCleanup(scope.tearDown)
        scope.configure("100000")
        sources = synthetic_nine()
        self.assertGreater(sum(len(base64.b64encode(source["payload"])) for source in sources), 25 * 1024 * 1024)
        originals = {source["sha256"] for source in sources}
        concept = fixtures.fixture.synthetic_png((1776, 2368), "#587961")
        concept_sha = hashlib.sha256(concept).hexdigest()
        bridges, observed, wire, assertions, concepts = [], [], [], [], []

        class Witness(runtime.Bridge):
            def __init__(inner, **kwargs):
                super().__init__(**kwargs)
                bridges.append(inner)

            def model(inner, payload, stage="design"):
                try:
                    if not observed:
                        hashes = runtime._images_in(payload)
                        self.assertEqual(len(hashes), 9,
                            "Actual SDK's first request dropped original-photo inspection pixels")
                        previews = inner.inspection_previews
                        self.assertEqual(set(previews), originals)
                        self.assertEqual(hashes, {item["sha256"] for item in previews.values()})
                        self.assertFalse(hashes & originals, "Preview bytes must not be labelled with original raw SHA")
                        self.assertFalse(inner.inspected_sources)
                        for item in previews.values():
                            image = (inner.directory / item["path"]).read_bytes()
                            self.assertEqual(hashlib.sha256(image).hexdigest(), item["sha256"])
                            self.assertLessEqual(len(base64.b64encode(image)), 1024 * 1024)
                            with Image.open(io.BytesIO(image)) as decoded:
                                self.assertLessEqual(max(decoded.size), 1600)
                    observed.append(payload)
                    return super().model(payload, stage=stage)
                except AssertionError as error:
                    assertions.append(error)
                    raise

        def transport(request):
            payload = json.loads(request.content)
            wire.append(payload)
            turn = len(wire)
            if turn == 1:
                return httpx.Response(200, json=model_reply(turn, [("cover_seedream", {"prompt": "Synthetic composition; preserve originals."})]))
            self.assertEqual(set(bridges[0].inspected_sources), originals)
            if turn == 2:
                return httpx.Response(200, json=model_reply(turn, [("cover_view", {"path": "reference/composition-reference.png"})]))
            self.assertEqual(turn, 3, "UNKNOWN must never retry")
            self.assertIn(concept_sha, runtime._images_in(payload), "Concept inspection must retain actual raw bytes")
            raise httpx.ReadTimeout("synthetic inspection UNKNOWN", request=request)

        def concept_stub(**kwargs):
            concepts.append(kwargs["call_id"])
            self.assertEqual(kwargs["source_images"], [source["payload"] for source in sources])
            return concept, {"call_id": kwargs["call_id"], "stage": "image", "status": "responded"}

        def checked_transport(request):
            try:
                return transport(request)
            except AssertionError as error:
                assertions.append(error)
                raise

        with tempfile.TemporaryDirectory(prefix="cover-inspection-sdk-") as folder, \
                mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": folder,
                    "NOTEAI_ARK_API_KEY": "offline-inspection-no-supplier", "NOTEAI_MODEL_CAPACITY_ENABLED": "0"}), \
                mock.patch.object(fixtures.billing, "_pricing_snapshot", side_effect=price_fixture(fixtures.billing._pricing_snapshot)), \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=concept_stub):
            hooks = runtime.cover_runtime.RuntimeHooks(lambda *_: None, lambda *_: None, lambda *_: None)
            try:
                runtime.run_cover(job_id=scope.task["job_id"], user_id=scope.owner,
                    report={"title": "原照独立图层中文排字测试", "body": "Synthetic fixture", "title_variants": []},
                    sources=sources, hooks=hooks, model_transport=httpx.MockTransport(checked_transport), bridge_class=Witness)
            except BaseException as error:
                if assertions:
                    raise assertions[0]
                self.assertIsInstance(error, provider.CoverAgentProviderError)
                self.assertTrue(error.outcome_unknown)
            else:
                self.fail("The one synthetic UNKNOWN must stop this technical scenario")
        self.assertEqual((len(wire), len(concepts)), (3, 1))
        self.assertEqual(set(bridges[0].inspected_sources), originals)
        rows = fixtures.db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=? ORDER BY created_at,id",
            (scope.claim["charge"]["usage_id"],))
        self.assertEqual([(row["state"], row["http_status"]) for row in rows], [("responded", 200)] * 2 + [("unknown", None)])
        print("COVER_INSPECTION_SDK_PROOF=" + json.dumps({"actual_sdk": True,
            "first_request_nine_previews": True, "preview_base64_at_most_1MiB": True,
            "original_inspection_known_200": 9, "original_raw_SHA_fabricated": False,
            "concept_raw_unchanged": True, "mock_200": 2, "unknown_once": 1,
            "real_supplier_calls": 0, "merchant_quality_acceptance": False}, sort_keys=True))


class InspectionPreviewTrustTests(unittest.TestCase):
    def test_known200_only_coverage_unknown_preserves_and_tampered_preview_rejected(self):
        scope = fixtures.budget_fixture.CoverVerificationBudgetTests()
        scope.setUp()
        self.addCleanup(scope.tearDown)
        scope.configure("100000")
        wire = []
        with tempfile.TemporaryDirectory(prefix="inspection-trust-") as folder, \
                mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "offline-inspection-trust",
                    "NOTEAI_MODEL_CAPACITY_ENABLED": "0"}), \
                mock.patch.object(fixtures.billing, "_pricing_snapshot", side_effect=price_fixture(fixtures.billing._pricing_snapshot)):
            directory = Path(folder)
            sources, previews = [], []
            for index, color in enumerate(("#587961", "#874956")):
                body = fixtures.fixture.synthetic_png((2000, 1600), color)
                source = {"media_ref": "trusted-" + str(index), "payload": body,
                    "path": "assets/source-" + str(index) + ".png", "sha256": hashlib.sha256(body).hexdigest()}
                sources.append(source)
                previews.append(runtime._prepare_inspection_source(source, index, directory))

            def transport(request):
                wire.append(request)
                if len(wire) == 1:
                    return httpx.Response(200, json=model_reply(1))
                raise httpx.ReadTimeout("synthetic trust unknown", request=request)

            bridge = runtime.Bridge(job_id=scope.task["job_id"], directory=directory,
                sources=sources, hooks=mock.Mock(), model_transport=httpx.MockTransport(transport))
            bridge._register_inspection_previews(previews)
            bridge.request_deadline = time.time() + 1200

            def payload(index):
                body = (directory / previews[index]["path"]).read_bytes()
                return {"model": provider.MODEL, "messages": [{"role": "user", "content": [
                    runtime.ark_media.image_part(body), {"type": "text", "text": "Synthetic inspection"}]}],
                    "max_completion_tokens": 1024, "stream": False}

            bridge.model(payload(0))
            before = dict(bridge.inspected_sources)
            self.assertEqual(set(before), {sources[0]["sha256"]})
            self.assertEqual(before[sources[0]["sha256"]]["image_sha256"], previews[0]["sha256"])
            self.assertNotIn(sources[0]["sha256"], bridge.seen_images)
            with self.assertRaises(provider.CoverAgentProviderError) as stopped:
                bridge.model(payload(1))
            self.assertTrue(stopped.exception.outcome_unknown)
            self.assertEqual(bridge.inspected_sources, before)
            self.assertEqual(len(wire), 2)
            file = directory / previews[1]["path"]
            file.chmod(0o600)
            file.write_bytes(fixtures.fixture.synthetic_png((200, 160), "#FFFFFF"))
            other = runtime.Bridge(job_id=scope.task["job_id"], directory=directory,
                sources=sources, hooks=mock.Mock())
            with self.assertRaisesRegex(runtime.cover_runtime.CoverRuntimeError, "COVER_AGENT_INSPECTION_PREVIEW_INVALID"):
                other._register_inspection_previews(previews)
            self.assertFalse(other.inspection_previews)
        print("COVER_INSPECTION_TRUST_PROOF=" + json.dumps({"known200_only": True,
            "unknown_preserves_previous_coverage": True, "tampered_preview_rejected": True,
            "original_SHA_not_fabricated": True, "mock_calls": 2, "real_supplier_calls": 0}, sort_keys=True))


class InspectionPreviewResourcesTests(unittest.TestCase):
    def bounded_wait(self):
        import model_admission
        import public_product
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "1",
                "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_BUFFER_MIB": "4"}):
            manager = model_admission.Admission(model_admission.Limits(media_workers=1,
                operations=4, pending_calls=16, queue_seconds=.15))
            owner, _ = manager.register("buffer-owner", str(uuid.uuid4()), route="/covers")
            operation, _ = manager.register("bounded-preview", str(uuid.uuid4()), route="/covers")
            ticket = manager.buffers.acquire(owner, str(uuid.uuid4()), "media_buffer", weight=4 * 1024 * 1024)
            invocation = public_product.Invocation("bounded-preview", str(uuid.uuid4()), route="/covers")
            invocation.admission_state = operation
            marker = public_product._invocation.set(invocation)
            started = time.monotonic()
            try:
                with mock.patch.object(model_admission, "current", return_value=manager):
                    with self.assertRaisesRegex(public_product.TrialProviderStopped, "MODEL_QUEUE_WAIT_EXCEEDED"):
                        runtime._prepare_inspection_preview(fixtures.fixture.synthetic_png((14, 14), "#587961"))
                self.assertLess(time.monotonic() - started, .8)
                self.assertFalse(manager.media.active)
                self.assertFalse(manager.calls.active)
            finally:
                public_product._invocation.reset(marker)
                manager.buffers.release(ticket)
                manager.finish(owner); manager.finish(operation)
            self.assertFalse(manager.buffers.active)
            self.assertFalse(manager.buffers.waiting)
            self.assertFalse(manager.operations)

    def mixed_order(self, order):
        import model_admission
        import public_product
        small = fixtures.fixture.synthetic_png((14, 14), "#587961")
        held, proceed, progressed = threading.Event(), threading.Event(), threading.Event()
        errors, completed = [], []
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "1",
                "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_BUFFER_MIB": "4"}):
            manager = model_admission.Admission(model_admission.Limits(media_workers=1,
                operations=4, pending_calls=16, queue_seconds=3))
            operations = [manager.register(order + str(i), str(uuid.uuid4()), route="/covers")[0] for i in range(2)]

            async def counterpart():
                # The existing ordinary-image and video resource contracts use
                # these opposite orders. Exercise the real async helpers.
                first = public_product.media_worker_slot(0) if order == "image" else public_product.media_buffer_slot(2 * 1024 * 1024)
                second = public_product.media_buffer_slot(2 * 1024 * 1024) if order == "image" else public_product.media_worker_slot(0)
                async with first:
                    held.set()
                    if not proceed.wait(5):
                        raise AssertionError("Contender was not released")
                    async with second:
                        progressed.set()

            def worker(index):
                invocation = public_product.Invocation(order + str(index), str(uuid.uuid4()), route="/covers")
                invocation.admission_state = operations[index]
                marker = public_product._invocation.set(invocation)
                try:
                    if index == 0:
                        asyncio.run(counterpart())
                    else:
                        runtime._prepare_inspection_preview(small)
                    completed.append(index)
                except BaseException as error:
                    errors.append(error)
                finally:
                    public_product._invocation.reset(marker)
                    manager.finish(operations[index])

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
            with mock.patch.object(model_admission, "current", return_value=manager):
                try:
                    threads[0].start()
                    self.assertTrue(held.wait(3))
                    threads[1].start()
                    until = time.monotonic() + 3
                    while not (manager.media.waiting or manager.buffers.waiting) and time.monotonic() < until:
                        time.sleep(.005)
                    self.assertTrue(manager.media.waiting or manager.buffers.waiting)
                    proceed.set()
                    self.assertTrue(progressed.wait(3), "Preview created a cycle with the real " + order + " resource order")
                finally:
                    proceed.set()
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(4)
                    for operation in operations:
                        manager.cancel(operation)
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(2)
            self.assertFalse(errors, repr(errors))
            self.assertEqual(set(completed), {0, 1})
            for queue in (manager.calls, manager.media, manager.buffers):
                self.assertFalse(queue.active)
                self.assertFalse(queue.waiting)
            self.assertFalse(manager.operations)

    def test_two_real_preparations_release_cpu_buffers_and_cancel_without_remote_permits(self):
        import model_admission
        import public_product
        body = fixtures.fixture.synthetic_png((2000, 1600), "#587961")
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        local = threading.local()
        failures, outputs = {}, {}
        original_open = Image.open
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "1",
                "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64", "NOTEAI_MODEL_BUFFER_MIB": "256"}):
            manager = model_admission.Admission(model_admission.Limits(media_workers=2,
                operations=4, pending_calls=16))
            operations = [manager.register("preview-owner-" + str(index), str(uuid.uuid4()), route="/covers")[0]
                for index in range(3)]

            def opened(*args, **kwargs):
                local.calls = getattr(local, "calls", 0) + 1
                if local.index < 2 and local.calls == 2:
                    entered[local.index].set()
                    if not release.wait(10):
                        raise AssertionError("Real preview worker was not released")
                return original_open(*args, **kwargs)

            def prepare(index):
                local.index, local.calls = index, 0
                invocation = public_product.Invocation("preview-owner-" + str(index), str(uuid.uuid4()), route="/covers")
                invocation.admission_state = operations[index]
                marker = public_product._invocation.set(invocation)
                try:
                    outputs[index] = runtime._prepare_inspection_preview(body)
                except BaseException as error:
                    failures[index] = error
                finally:
                    public_product._invocation.reset(marker)
                    manager.finish(operations[index])

            threads = [threading.Thread(target=prepare, args=(index,)) for index in range(3)]
            with mock.patch.object(model_admission, "current", return_value=manager), \
                    mock.patch.object(Image, "open", side_effect=opened):
                try:
                    threads[0].start(); threads[1].start()
                    self.assertTrue(all(event.wait(5) for event in entered))
                    self.assertEqual(len(manager.media.active), 2)
                    self.assertEqual(len(manager.calls.active), 0)
                    self.assertEqual(len(manager.buffers.active), 2)
                    threads[2].start()
                    until = time.monotonic() + 5
                    while not manager.media.waiting and time.monotonic() < until:
                        time.sleep(.01)
                    self.assertTrue(manager.media.waiting)
                    manager.cancel(operations[2])
                    threads[2].join(5)
                    self.assertFalse(threads[2].is_alive())
                finally:
                    release.set()
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(10)
            self.assertEqual(set(outputs), {0, 1})
            self.assertEqual(set(failures), {2})
            self.assertIn("MODEL_OPERATION_CANCELLED", str(failures[2]))
            for queue in (manager.calls, manager.media, manager.buffers):
                self.assertFalse(queue.active)
                self.assertFalse(queue.waiting)
            self.assertFalse(manager.operations)
        self.mixed_order("image")
        self.mixed_order("video")
        self.bounded_wait()
        print("COVER_INSPECTION_RESOURCES_PROOF=" + json.dumps({"actual_Pillow_preparations": 2,
            "CPU_max": 2, "remote_held": 0, "cancelled_waiter": 1,
            "mixed_image_media_then_buffer": True, "mixed_video_buffer_then_media": True,
            "original_total_queue_bound_preserved": True,
            "all_CPU_buffer_and_operation_leases_released": True, "real_supplier_calls": 0}, sort_keys=True))
