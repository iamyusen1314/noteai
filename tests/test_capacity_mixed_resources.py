"""One shared local API fixture: 100 image observations plus real SDK render.

Ten synthetic users each submit nine P1 observations and one P0 observation.
HTTP is MockTransport; the SDK/CLI/Chromium and image handling are real. This
measures coexistence and bounds, never supplier throughput or merchant quality.
"""
import asyncio
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import random
import resource
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from tests import test_private_storage_recovery as storage_fixture
from tests import test_cover_agent_source_binding as sdk_fixture
from tests.test_generation_multiuser_admission import api, ark, admission, db, billing, public
import postdelivery


def _resources():
    """The QA Python process, not container PID 1. Peak counters are cumulative."""
    result = {"python_pid": os.getpid(), "python_threads": threading.active_count(),
              "process_ru_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                  (1 if sys.platform == "darwin" else 1024)}
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text().splitlines():
            if line.startswith(("VmRSS:", "Threads:")):
                key, value = line.split(":", 1)
                result[key] = int(value.strip().split()[0]) * (1024 if key == "VmRSS" else 1)
    root = Path("/sys/fs/cgroup")
    for name in ("memory.current", "memory.peak", "memory.max", "memory.swap.max", "pids.current", "pids.max", "cpu.max"):
        path = root / name
        if path.is_file():
            value = path.read_text().strip()
            result[name] = int(value) if value.isdigit() else value
    for name in ("memory.events", "cpu.stat"):
        path = root / name
        if path.is_file():
            result[name] = {k: int(v) for k, v in (line.split() for line in path.read_text().splitlines())}
    return result


def _descendants(pid):
    """Linux descendants of the owned Node host, including Chromium processes."""
    result, pending = set(), [pid]
    while pending:
        parent = pending.pop()
        tasks = Path("/proc") / str(parent) / "task"
        if not tasks.is_dir():
            continue
        try:
            for task in tasks.iterdir():
                try:
                    children = (task / "children").read_text().split()
                except OSError:
                    continue
                for child in map(int, children):
                    if child not in result and child != pid:
                        result.add(child)
                        pending.append(child)
        except OSError:
            continue
    return result


class MixedImageAndRenderResourcesTests(unittest.TestCase):
    def test_ten_users_one_hundred_image_observations_share_memory_with_actual_sdk_render(self):
        runtime, artifacts, provider = sdk_fixture.runtime, sdk_fixture.artifacts, sdk_fixture.provider
        if not runtime.environment_ready():
            raise AssertionError("Explicit approved Node/SDK/Chromium environment required; no skip or mock-render pass")
        remote = int(os.environ.get("NOTEAI_CAPACITY_MIXED_REMOTE", "64"))
        self.assertIn(remote, (16, 64))
        proof = {"state": "STARTED", "remote_limit": remote, "external_supplier_calls": 0,
                 "quality_is_synthetic": True, "full_report_or_production_proof": False,
                 "process_role": "in-process actual API helpers; not a running Uvicorn socket"}
        stage_points = {"before_fixture": _resources()}
        fixture = storage_fixture.PrivateStorageRecoveryContractTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        root = Path(fixture.temp.name)
        backend = api._private_storage.LocalDirectoryObjectBackend(root / "objects")
        api._private_storage.configure_object_backend(backend, key_epoch="mixed-resource-fixture")
        remote_ready, release_wire = threading.Event(), threading.Event()
        gate = threading.Lock()
        state = {"wire_active": 0, "wire_peak": 0, "wire_count": 0, "wire_body_bytes_active": 0,
                 "wire_body_bytes_peak": 0, "prepared": 0, "prepared_before_release": 0,
                 "cpu_working": 0, "cpu_peak": 0}
        samples, beats, first_service, candidates, stopped, hosts, child_pids = [], [], {}, [], [], [], set()
        material_resident = []
        env = {"NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
               "NOTEAI_MODEL_CAPACITY_SCOPE": "ark-primary", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
               "NOTEAI_MODEL_REMOTE_CONCURRENCY": str(remote), "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2",
               "NOTEAI_MODEL_BUFFER_MIB": "256", "NOTEAI_MODEL_ADMITTED_OPERATIONS": "100",
               "NOTEAI_MODEL_PENDING_CALLS": "256", "NOTEAI_MODEL_QUEUE_SECONDS": "1800",
               "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "30",
               "NOTEAI_ARK_API_KEY": "synthetic-offline-only",
               "NOTEAI_COVER_AGENT_STATE_ROOT": str(root / "agent")}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(socket.socket, "connect", side_effect=AssertionError("No external socket allowed")), \
             mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No external socket allowed")):
            # Warm the exact production getter from already-present artifacts.
            # Suppress only acquisition: neither startup, ensure/download nor a
            # provider may run. The getter still enforces its original report
            # policy and constructs the real LightGBM Booster from local bytes.
            warm_before = _resources()
            with mock.patch.object(api, "_model_artifacts_ensured", True), \
                 mock.patch.object(api, "ensure_model_artifacts",
                    side_effect=AssertionError("Artifact download forbidden in resource QA")) as acquire:
                model = api.get_v04_composite_model() if api.USE_V04_COMPOSITE else api.get_model()
            acquire.assert_not_called()
            self.assertIsNotNone(model, "Existing production-approved local model artifact required")
            self.assertEqual(type(model).__module__, "lightgbm.basic")
            self.assertEqual(type(model).__qualname__, "Booster")
            model_path = Path(api._v04_model_signature[0] if api.USE_V04_COMPOSITE else api.MODEL_PATH)
            self.assertTrue(model_path.is_file())
            def file_identity(path):
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}
            proof["local_model"] = {"loaded": True, "class": type(model).__module__ + "." + type(model).__qualname__,
                "getter": "get_v04_composite_model" if api.USE_V04_COMPOSITE else "get_model",
                "model": file_identity(model_path), "before_warm": warm_before,
                "after_warm": _resources(), "ensure_calls": 0, "download_calls": 0,
                "whole_startup_called": False}
            if api.USE_V04_COMPOSITE:
                proof["local_model"]["report"] = file_identity(api.V04_TRAIN_REPORT_PATH)
            stage_points["after_local_production_model_warm"] = _resources()
            manager = admission.Admission()
            self.addCleanup(manager.close_remote_workers)
            with mock.patch.object(admission, "_instance", manager):
                db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
                # Generate once, retain a single immutable payload for the normal
                # upload calls. LocalDirectoryBackend, not 100 in-memory copies.
                raw = random.Random(31).randbytes(1100 * 800 * 3)
                out = io.BytesIO()
                Image.frombytes("RGB", (1100, 800), raw).save(out, "JPEG", quality=90)
                photo = out.getvalue()
                del raw, out
                sources = []
                for index in range(9):
                    body = sdk_fixture.fixture.synthetic_png((600, 400), "#" + format(0x365170 + index * 100, "06x"))
                    sources.append({"media_ref": "mixed-synthetic-" + str(index),
                                    "payload": body, "sha256": artifacts.digest(body)})
                concept = sdk_fixture.fixture.synthetic_png((1776, 2368), "#a1a8b1")
                stage_points["after_material_generation"] = _resources()
                material_resident.append(len(photo) + sum(len(x["payload"]) for x in sources) + len(concept))
                cases = []
                for index in range(10):
                    user = "mixed-owner-%02d" % index
                    fixture.create_user(user)
                    ref = api._private_storage.store_media_bytes(user, purpose="image", content_type="image/jpeg",
                            payload=photo, item_count=1)
                    claim = postdelivery.reserve_claim(user_id=user, operation="generate",
                            request_id="mixed-original-" + user, payload={"fixture": True})
                    operation, _ = manager.register(user, user, route="/generate/stream")
                    inv = public.Invocation(user, claim["request_id"], route="/generate/stream", admission_state=operation)
                    cases.append((user, ref, claim, inv, operation))
                for index in range(4):
                    fixture.create_user("mixed-upload-%d" % index)
                gc.collect()
                stage_points["material_stored_and_gc_before_pipeline"] = _resources()
                p1_original = api._prepare_buffered_image_observation
                p0_original = api._prepare_buffered_cover_vision
                marker = public._invocation.set(cases[0][3])
                try:
                    initial_bound = p1_original(cases[0][1].id, "休闲娱乐体验", "合成资源验证")[1]
                finally:
                    public._invocation.reset(marker)
                self.assertLess(initial_bound * remote, manager.buffers.capacity,
                                "Fixture must reach remote bound before byte backpressure")
                self.assertGreater(initial_bound * 100, manager.buffers.capacity,
                                   "Fixture must expose pending work instead of materializing all 100 bodies")
                proof["material"] = {"photo_dimensions": [1100, 800], "photo_bytes": len(photo),
                    "immutable_python_payload_bytes": material_resident[0], "private_source_refs": 10,
                    "object_directory_bytes_before_pipeline": sum(p.stat().st_size for p in backend.root.rglob("*") if p.is_file()),
                    "prepared_P1_body_bound_bytes": initial_bound,
                    "note": "One generated JPEG retained, 10 owner objects on isolated disk; not 100 body copies. Cgroup tmpfs/pagecache, if present, remains included."}

                def preparation(function, *args):
                    with gate:
                        state["cpu_working"] += 1
                        state["cpu_peak"] = max(state["cpu_peak"], state["cpu_working"])
                    try:
                        answer = function(*args)
                        with gate:
                            state["prepared"] += 1
                            if not release_wire.is_set():
                                state["prepared_before_release"] += 1
                        return answer
                    finally:
                        with gate:
                            state["cpu_working"] -= 1

                def supplier(request):
                    # Parse only the discriminator; retain no second body copy
                    # while the actual prepared/request payload remains live.
                    maximum = json.loads(request.content)["max_tokens"]
                    length = len(request.content)
                    invocation = public._invocation.get()
                    with gate:
                        state["wire_count"] += 1
                        state["wire_active"] += 1
                        state["wire_peak"] = max(state["wire_peak"], state["wire_active"])
                        state["wire_body_bytes_active"] += length
                        state["wire_body_bytes_peak"] = max(state["wire_body_bytes_peak"], state["wire_body_bytes_active"])
                        first_service.setdefault(invocation.user_id, time.monotonic())
                        if state["wire_active"] == remote:
                            remote_ready.set()
                    try:
                        if not release_wire.wait(90):
                            raise AssertionError("Controlled mixed HTTP was not released")
                        time.sleep(.02)
                        answer = ({"has_text_overlay": False, "text_prominence": .1,
                                   "composition_score": .7, "aesthetic_score": .8,
                                   "emotion_intensity": .6, "visual_clarity": .9} if maximum == 2048
                                  else "原始合成图片已真实读取，模型内容为技术桩。")
                        return httpx.Response(200, json={"model": ark.MODEL,
                            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                      "prompt_tokens_details": {"cached_tokens": 0}},
                            "choices": [{"finish_reason": "stop", "message": {
                                "content": json.dumps(answer) if isinstance(answer, dict) else answer}}]})
                    finally:
                        with gate:
                            state["wire_active"] -= 1
                            state["wire_body_bytes_active"] -= length

                def client(**kwargs):
                    return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

                class MixedBridge(sdk_fixture.CanonicalSourceScriptedBridge):
                    case = "original"
                    instances = []
                    def tool(bridge, request):
                        if request.get("name") == "cover_render":
                            if not remote_ready.wait(60):
                                raise AssertionError("Actual renderer did not overlap held model HTTP")
                            with gate:
                                proof["wire_active_at_actual_render_dispatch"] = state["wire_active"]
                        return super().tool(request)

                def concept_stub(**kwargs):
                    if kwargs["source_images"] != [s["payload"] for s in sources]:
                        raise AssertionError("Actual frozen synthetic originals were changed")
                    record = {"stage": "image", "status": "responded", "provider": "offline-stub", "call_id": kwargs["call_id"]}
                    kwargs["before_call"]("image", kwargs["call_id"], {})
                    kwargs["on_call"](record)
                    return concept, record

                original_popen, original_stop = runtime.subprocess.Popen, runtime._stop_host
                def popen(*args, **kwargs):
                    process = original_popen(*args, **kwargs)
                    command = args[0] if args else kwargs.get("args", [])
                    if any(str(x).endswith("cover_agent_host/worker.mjs") for x in command):
                        hosts.append(process)
                    return process
                def stop_host(process):
                    original_stop(process)
                    stopped.append({"pid": process.pid, "reaped": process.poll() is not None})
                def on_candidate(snapshot, body):
                    candidates.append({"png_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                        "qc_present": snapshot["qc"] is not None})
                def render():
                    hooks = sdk_fixture.cover_runtime.RuntimeHooks(lambda *_: None, lambda *_: None,
                        lambda *_: None, on_candidate=on_candidate)
                    job = str(uuid.uuid4())
                    try:
                        result = runtime.run_cover(job_id=job, user_id="synthetic-cover-owner", sources=sources,
                            hooks=hooks, report={"title": "原照独立图层中文排字测试", "body": "技术资源验证，不代表商家成品审美验收。", "title_variants": []},
                            bridge_class=MixedBridge)
                        return {"png_bytes": len(result.final_bytes), "png_sha256": artifacts.digest(result.final_bytes),
                            "input_sources": len(result.layout["input_source_hashes"]), "candidates": candidates}
                    finally:
                        runtime.cleanup_workspace(job)

                async def observe(case, image_index):
                    user, ref, claim, inv, _operation = case
                    im = public._invocation.set(inv)
                    um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
                    try:
                        if image_index == 9:
                            return await api._bounded_extract_cover(ref.id, True)
                        return await api._generation_image_observation(ref.id, "休闲娱乐体验", "合成资源验证", image_index)
                    finally:
                        billing._ACTIVE_USAGE_ID.reset(um)
                        public._invocation.reset(im)

                async def upload(index):
                    user = "mixed-upload-%d" % index
                    marker = public._invocation.set(public.Invocation(user, "mixed-upload", route="/upload-image"))
                    begin = time.monotonic()
                    try:
                        answer = await api.upload_image(UploadFile(file=io.BytesIO(photo), filename="synthetic.jpg",
                                headers=Headers({"content-type": "image/jpeg"})), {"id": user}, [])
                        ref, body = api._private_storage.load_media_bytes(answer["media_ref"], user_id=user, purpose="image")
                        self.assertTrue(body)
                        self.assertEqual((answer["width"], answer["height"]), (1100, 800))
                        return {"seconds": time.monotonic() - begin, "bytes": len(body)}
                    finally:
                        public._invocation.reset(marker)

                def snapshot():
                    sample = {"t": time.monotonic(), **_resources()}
                    for name in ("calls", "media", "buffers"):
                        queue = getattr(manager, name)
                        with queue.lock:
                            sample[name] = {"active": len(queue.active), "pending": len(queue._tickets()),
                                            "weight": sum(t.weight for t in queue.active.values())}
                    with gate:
                        sample.update(state)
                    for process in hosts:
                        child_pids.update(_descendants(process.pid))
                    sample["owned_node_pids"] = [p.pid for p in hosts if p.poll() is None]
                    sample["remote_threads"] = sum(t.name.startswith("noteai-model-io") for t in threading.enumerate())
                    samples.append(sample)

                async def scenario():
                    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=4,
                            thread_name_prefix="mixed-local-cpu"))
                    stop = asyncio.Event()
                    async def source():
                        await stop.wait()
                        if False:
                            yield ""
                    async def heartbeat():
                        async for chunk in api._timed_sse_stream(source(), operation="generate", success_types={"complete"}):
                            if json.loads(chunk.removeprefix("data: ").strip())["type"] == "heartbeat":
                                beats.append(time.monotonic())
                    async def sample_loop():
                        while not stop.is_set():
                            snapshot()
                            await asyncio.sleep(.1)
                    async def wait_remote():
                        while not remote_ready.is_set():
                            await asyncio.sleep(.01)
                    watcher, sampler = asyncio.create_task(heartbeat()), asyncio.create_task(sample_loop())
                    observations = [asyncio.create_task(observe(case, index)) for index in range(10) for case in cases]
                    rendering = asyncio.create_task(asyncio.to_thread(render))
                    uploads = []
                    started = time.monotonic()
                    try:
                        await asyncio.wait_for(wait_remote(), 60)
                        beat_before = len(beats)
                        uploads = [asyncio.create_task(upload(i)) for i in range(4)]
                        render_result = await asyncio.wait_for(asyncio.shield(rendering), 120)
                        self.assertGreater(len(beats), beat_before, "SSE heartbeat stopped during remote/render coexistence")
                        self.assertEqual(proof["wire_active_at_actual_render_dispatch"], remote)
                        snapshot()
                        self.assertLess(state["prepared_before_release"], 100,
                                        "All pending image bodies expanded before byte admission")
                        release_wire.set()
                        results = await asyncio.wait_for(asyncio.gather(*observations), 90)
                        upload_results = await asyncio.wait_for(asyncio.gather(*uploads), 30)
                        self.assertEqual(len(results), 100)
                        self.assertEqual(sum(isinstance(x, tuple) for x in results), 10)
                        proof.update(render=render_result, uploads=upload_results, elapsed_seconds=time.monotonic() - started)
                    finally:
                        release_wire.set()
                        await asyncio.gather(*observations, *uploads, rendering, return_exceptions=True)
                        stop.set()
                        await asyncio.gather(watcher, sampler, return_exceptions=True)
                        for _u, _r, _c, _i, operation in cases:
                            manager.finish(operation)
                    snapshot()

                with mock.patch.object(ark, "_client", side_effect=client), \
                     mock.patch.object(api, "_prepare_buffered_image_observation", side_effect=lambda *a: preparation(p1_original, *a)), \
                     mock.patch.object(api, "_prepare_buffered_cover_vision", side_effect=lambda *a: preparation(p0_original, *a)), \
                     mock.patch.object(provider, "complete", side_effect=AssertionError("Physical design supplier forbidden")), \
                     mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=concept_stub), \
                     mock.patch.object(runtime.subprocess, "Popen", side_effect=popen), \
                     mock.patch.object(runtime, "_stop_host", side_effect=stop_host), \
                     mock.patch.object(api, "_SSE_HEARTBEAT_SECONDS", .02):
                    asyncio.run(scenario())
                manager.close_remote_workers()
                self.assertEqual(state["wire_count"], 100)
                self.assertEqual(state["wire_peak"], remote)
                self.assertLessEqual(state["cpu_peak"], 2)
                self.assertEqual(len(first_service), 10)
                self.assertEqual(len(candidates), 2)
                self.assertTrue(candidates[-1]["qc_present"])
                self.assertEqual(len(stopped), 1)
                self.assertTrue(stopped[0]["reaped"])
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded' AND http_status=200")[0], 100)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 100)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state IN ('unknown','dispatched')")[0], 0)
                for _u, _r, claim, _i, _o in cases:
                    row = db.fetchone("SELECT complete_applied,refund_applied FROM idempotency_requests WHERE id=?", (claim["request_id"],))
                    self.assertEqual(tuple(row), (0, 0))
                for name in ("calls", "media", "buffers"):
                    queue = getattr(manager, name)
                    self.assertEqual(queue.active, {})
                    self.assertEqual(queue._tickets(), [])
                self.assertEqual(manager.operations, {})
                max_buffer = max(s["buffers"]["weight"] for s in samples)
                self.assertLessEqual(max_buffer, 256 * 1024 * 1024)
                final = _resources()
                if os.environ.get("NOTEAI_CAPACITY_LINUX_PROFILE_REQUIRED") == "1":
                    self.assertEqual(sys.platform, "linux")
                    self.assertEqual(final["memory.max"], 3 * 1024 ** 3)
                    self.assertEqual(final["memory.swap.max"], 0)
                    quota, period = map(int, final["cpu.max"].split())
                    self.assertEqual(quota, 2 * period)
                    for event in ("oom", "oom_kill"):
                        self.assertEqual(final["memory.events"].get(event, 0), 0)
                proof.update(state="LOCAL_SYNTHETIC_MIXED_RESOURCE_PASS", platform=sys.platform,
                    node=subprocess.check_output([os.environ.get("NOTEAI_COVER_NODE", "node"), "--version"], text=True).strip(),
                    linux_profile_required=os.environ.get("NOTEAI_CAPACITY_LINUX_PROFILE_REQUIRED") == "1",
                    stage_points=stage_points, final_resources=final, sample_count=len(samples),
                    maxima={"wire_active": state["wire_peak"], "cpu_working": state["cpu_peak"],
                        "weighted_buffer_bytes": max_buffer, "prepared_before_release": state["prepared_before_release"],
                        "pipeline_sampled_memory_current": max((s["memory.current"] for s in samples if "memory.current" in s), default=None),
                        "pipeline_sampled_python_RSS": max((s["VmRSS"] for s in samples if "VmRSS" in s), default=None),
                        "pipeline_process_cumulative_ru_maxrss": max(s["process_ru_maxrss_bytes"] for s in samples),
                        "python_threads": max(s["python_threads"] for s in samples),
                        "remote_threads": max(s["remote_threads"] for s in samples),
                        "heartbeat_gap_seconds": max((b - a for a, b in zip(beats, beats[1:])), default=0)},
                    queue_peaks={name: max(s[name]["pending"] for s in samples) for name in ("calls", "media", "buffers")},
                    observed_owned_node_pids=[p.pid for p in hosts], observed_linux_descendant_pids=sorted(child_pids),
                    stopped_hosts=stopped, physical_known_200=100, model_meter_rows=100,
                    user_final_settlements=0, user_refunds=0, first_service_users=len(first_service), heartbeat_count=len(beats),
                    limits={"media": manager.media.capacity, "buffers": manager.buffers.capacity,
                        "remote": manager.calls.capacity, "claude_rpm": manager.limits.claude_rpm,
                        "queue_seconds": manager.limits.queue_seconds},
                    limits_of_evidence=["100 pending image observations across 10 claims, not 100 completed reports or durable jobs",
                        "P1/P0 only: no real Claude/Kimi/Pro/Seedream wire, complete report save/settlement is separate",
                        "real synthetic SDK/CLI/capture with scripted design/QC, not merchant aesthetic acceptance",
                        "four normal upload handlers; ASGI aggregate stream budget separately verified, not claimed here",
                        "resource peak counters cumulative; original local production model warm, fixture generation, fixture object pagecache and sampled pipeline phase identified separately"])
                target = os.environ.get("NOTEAI_CAPACITY_MIXED_PROOF")
                if target:
                    Path(target).write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
                print("CAPACITY_MIXED_RESOURCES_PROOF=" + json.dumps(proof, ensure_ascii=False, sort_keys=True))
