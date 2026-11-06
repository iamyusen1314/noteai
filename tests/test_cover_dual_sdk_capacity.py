"""One controlled two-SDK cover lifecycle; never a supplier/quality benchmark.

The authorized R18 tar is an explicit sealed input. A separately labelled small
technical fixture can exercise this harness locally, but cannot produce merchant
or Linux capacity acceptance. Only this target is needed; old suites are reused.
"""
import asyncio
import base64
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import gc
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

import httpx

R18_TAR_SHA256 = "220b18ff10ed696234f51f6546bbf08b409884b126ce6b532ba0f85cf4ea773c"
R18_TAR_BYTES = 92631040


def digest(body):
    return hashlib.sha256(body).hexdigest()


def file_pin(path):
    hashed, size = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(block)
            size += len(block)
    return {"bytes": size, "sha256": hashed.hexdigest()}


def filesystem(path):
    path = Path(path).resolve()
    existing = path
    while not existing.exists():
        existing = existing.parent
    stat = os.statvfs(existing)
    result = {"exists": path.exists(), "total_bytes": stat.f_blocks * stat.f_frsize,
        "available_bytes": stat.f_bavail * stat.f_frsize, "available_inodes": stat.f_favail,
        "read_only": bool(stat.f_flag & getattr(os, "ST_RDONLY", 1)), "fs_type": None}
    info = Path("/proc/self/mountinfo")
    if info.is_file():
        matches = []
        for line in info.read_text().splitlines():
            left, right = line.split(" - ", 1)
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), left.split()[4])
            if existing == Path(mount) or Path(mount) in existing.parents:
                matches.append((len(mount), right.split()[0]))
        if matches:
            result["fs_type"] = max(matches)[1]
    return result


def resources(workspace):
    result = {"workspace_fs": filesystem(workspace), "browser_tmp_fs": filesystem("/tmp")}
    cg = Path("/sys/fs/cgroup")
    if not (cg / "memory.current").is_file():
        result["actual_linux_cgroup"] = False
        return result
    def count(name):
        return int((cg / name).read_text())
    def events(name):
        return {key: int(value) for key, value in
            (line.split() for line in (cg / name).read_text().splitlines())}
    states, threads = {}, 0
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            status = (process / "status").read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        state = next(line.split()[1] for line in status.splitlines() if line.startswith("State:"))
        states[state] = states.get(state, 0) + 1
        threads += int(next(line.split()[1] for line in status.splitlines() if line.startswith("Threads:")))
    result.update(actual_linux_cgroup=True, memory_current_bytes=count("memory.current"),
        memory_peak_bytes=count("memory.peak"), memory_max=(cg / "memory.max").read_text().strip(),
        memory_events=events("memory.events"), cpu_max=(cg / "cpu.max").read_text().strip(),
        pids_current=count("pids.current"), pids_max=(cg / "pids.max").read_text().strip(),
        pids_events=events("pids.events"), process_states=states, namespace_threads=threads)
    return result


def model_reply(turn, calls=None, text="Controlled local resource response; not visual acceptance."):
    message = {"role": "assistant", "content": text,
        "encrypted_content": "TEST_DUAL_SDK_OPAQUE_" + str(turn)}
    if calls:
        message["tool_calls"] = [{"id": "dual_" + str(turn) + "_" + str(index),
            "type": "function", "function": {"name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False)}}
            for index, (name, arguments) in enumerate(calls)]
    return {"id": "chatcmpl-dual-" + str(turn), "object": "chat.completion", "created": 1,
        "model": "doubao-seed-2-1-pro-260915", "choices": [{"index": 0,
            "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 20},
            "completion_tokens_details": {"reasoning_tokens": 15}}}


class DualSDKCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_actual_sdk_sessions_share_renderer_and_complete_private_lifecycles(self):
        supplied = os.environ.get("NOTEAI_COVER_DUAL_FIXTURE_TAR")
        if not supplied or not Path(supplied).is_file():
            self.skipTest("Explicit sealed real-material tar required; no merchant/LINUX result fabricated")
        kind = os.environ.get("NOTEAI_COVER_DUAL_FIXTURE_KIND", "authorized_R18_actual_fixture")
        self.assertIn(kind, {"authorized_R18_actual_fixture", "technical_harness_only"})
        expected = R18_TAR_SHA256 if kind == "authorized_R18_actual_fixture" else os.environ.get(
            "NOTEAI_COVER_DUAL_TECHNICAL_FIXTURE_SHA256", "")
        self.assertRegex(expected, r"^[a-f0-9]{64}$")
        tar_pin = file_pin(supplied)
        self.assertEqual(tar_pin["sha256"], expected)
        if kind == "authorized_R18_actual_fixture":
            self.assertEqual(tar_pin["bytes"], R18_TAR_BYTES)
        self.assertTrue(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES"), "Existing approved SDK required")
        self.assertTrue(Path(os.environ.get("EDITABLE_DESIGN_BROWSER", "")).is_file())
        parent = os.environ.get("NOTEAI_COVER_DUAL_STATE_ROOT")
        object_parent = os.environ.get("NOTEAI_COVER_DUAL_OBJECT_ROOT")
        strict_profile = os.environ.get("NOTEAI_COVER_DUAL_REQUIRE_PROFILE") == "1"
        if strict_profile:
            self.assertTrue(parent and object_parent,
                "Explicit production-equivalent workspace and isolated object-store medium required")
        with tempfile.TemporaryDirectory(prefix="dual-sdk-state-", dir=parent) as folder, \
                tempfile.TemporaryDirectory(prefix="dual-sdk-objects-", dir=object_parent) as objects, ExitStack() as stack:
            root = Path(folder)
            stack.enter_context(mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1",
                "NOTEAI_SQLITE_PATH": str(root / "import.sqlite"), "NOTEAI_PUBLIC_PRODUCT": "1",
                "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_CAPACITY_SCOPE": "ark-primary",
                "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64",
                "NOTEAI_MODEL_ADMITTED_OPERATIONS": "100", "NOTEAI_MODEL_PENDING_CALLS": "512",
                "NOTEAI_MODEL_OPERATIONS_PER_USER": "1", "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2",
                "NOTEAI_MODEL_BUFFER_MIB": "256", "NOTEAI_COVER_WORKER_SLOTS": "2",
                "NOTEAI_COVER_AGENT_STATE_ROOT": str(root / "workspaces"),
                "NOTEAI_ARK_API_KEY": "offline-only-no-supplier", "NOTEAI_POSTDELIVERY_SETTLEMENT": "1"}))
            for suffix in ("USER_ID", "SINCE_UTC", "MAX_MILLI"):
                os.environ.pop("NOTEAI_COVER_VERIFY_" + suffix, None)
            # Import only after the explicit local DB/environment is installed.
            from tests import test_cover_jobs as job_fixtures
            from tests import test_cover_agent_compound_render as compound
            fixture = job_fixtures.CoverJobsTests()
            fixture.setUp()
            stack.callback(fixture.tearDown)
            runtime, artifacts, provider = compound.runtime, compound.artifacts, compound.provider
            billing, db, storage = compound.inspection.fixtures.billing, compound.inspection.fixtures.db, job_fixtures.private_storage
            import model_admission as admission
            import public_product as public
            import cover_jobs as jobs
            import cover_service as service
            import cover_runtime
            # setUp's accounting fixture is intentionally local. Restore our
            # actual capacity mode after it sets the legacy default environment.
            os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "1"
            backend = storage.LocalDirectoryObjectBackend(Path(objects))
            storage.configure_object_backend(backend, key_epoch="dual-sdk-private-resource-fixture")
            manager = admission.Admission()
            stack.enter_context(mock.patch.object(admission, "_instance", manager))
            stack.callback(manager.close_remote_workers)
            self.assertEqual((manager.calls.capacity, manager.media.capacity), (64, 2))
            stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("No supplier network")))
            stack.enter_context(mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No supplier network")))
            stack.enter_context(mock.patch.object(billing, "_pricing_snapshot",
                side_effect=compound.inspection.price_fixture(billing._pricing_snapshot)))
            self.assertTrue(runtime.environment_ready(), "Actual approved SDK/Node/browser must be ready")
            node_version = subprocess.check_output([os.environ.get("NOTEAI_COVER_NODE", "node"), "--version"], text=True).strip()
            tested_source_pins = {name: file_pin(Path(runtime.ROOT) / name) for name in
                ("api.py", "cover_jobs.py", "cover_service.py", "cover_agent_artifacts.py",
                 "cover_agent_runtime.py", "cover_agent_host/host.mjs", "cover_editable/cli.mjs")}
            before = resources(root / "workspaces")
            object_fs = filesystem(objects)
            production_profile_equivalent = False
            if strict_profile:
                self.assertTrue(before["actual_linux_cgroup"])
                self.assertEqual(node_version, "v24.22.1")
                self.assertEqual((before["memory_max"], before["cpu_max"], before["pids_max"]),
                    (str(3 * 1024 ** 3), "200000 100000", "512"))
                pid1 = Path("/proc/1/status").read_text()
                self.assertRegex(pid1, r"Name:\s+(?:docker-init|tini)")
                self.assertEqual(before["workspace_fs"]["fs_type"], "ext4")
                self.assertEqual(object_fs["fs_type"], "ext4")
                self.assertFalse(before["workspace_fs"]["read_only"])
                self.assertFalse(object_fs["read_only"])
                self.assertEqual((before["browser_tmp_fs"]["fs_type"], before["browser_tmp_fs"]["total_bytes"]),
                    ("tmpfs", 256 * 1024 ** 2))
                production_profile_equivalent = True
            stage, lock, local = ["fixture"], threading.RLock(), threading.local()
            samples, sample_errors, points, host_rows, render_rows = [], [], {}, [], []
            sample_stop = threading.Event()
            renderer = {"active": 0, "peak": 0}
            resident = {}
            def sampled_point():
                value = resources(root / "workspaces")
                with manager.calls.lock, manager.media.lock, manager.buffers.lock:
                    value.update(media_active=len(manager.media.active), remote_active=len(manager.calls.active),
                        buffers_active_bytes=sum(ticket.weight for ticket in manager.buffers.active.values()))
                with lock:
                    value.update(stage=stage[0], renderer_active=renderer["active"])
                return value
            def sample():
                while not sample_stop.wait(.05):
                    try:
                        value = sampled_point()
                        with lock:
                            samples.append(value)
                    except BaseException as error:
                        sample_errors.append(type(error).__name__)
                        return
            sampler = threading.Thread(target=sample, name="owned-dual-sdk-resource-sampler")
            sampler.start()
            stack.callback(lambda: (sample_stop.set(), sampler.join(5)))
            # The source fixture is immutable. Backend copies are disk objects;
            # neither a global InMemory backend nor 100 synthetic byte copies.
            with tarfile.open(supplied, "r:") as tar:
                meta = json.loads(tar.extractfile("manifest.json").read())
                self.assertEqual(meta["schema"], "noteai.cover.r18.rss-fixture.v1")
                self.assertEqual(len(meta["sources"]), 9)
                raw_sources = []
                for item in meta["sources"]:
                    body = tar.extractfile(item["file"]).read()
                    self.assertEqual({"bytes": len(body), "sha256": digest(body)},
                        {key: item[key] for key in ("bytes", "sha256")})
                    raw_sources.append(body)
                original_bundle = tar.extractfile("bundle.bin").read()
                self.assertEqual({"bytes": len(original_bundle), "sha256": digest(original_bundle)},
                    {key: meta["bundle"][key] for key in ("bytes", "sha256")})
            restored = artifacts.restore(original_bundle, root / "fixture-design")
            frozen = json.loads((restored / "render-manifest.json").read_text())
            approved = meta["approved_titles"]
            html = (restored / "index.html").read_text()
            # R18 rev2 is a user edit. Replay the approved original title using
            # only an actual saved label's punctuation removal, never new facts.
            for layer in meta["layout"]["text_layers"]:
                if not any("".join(layer["text"].split()) in "".join(title.split()) for title in approved):
                    old, changed = layer["text"], layer["text"].replace("·", "")
                    self.assertTrue(any("".join(changed.split()) in "".join(title.split()) for title in approved))
                    self.assertTrue(old in html, "Saved label absent from sealed design")
                    html = html.replace(old, changed)
            file_names = ("index.html", "poster.json", "brief.md", "design-plan.md", "asset-plan.json", "prompts.md")
            packet = {"files": [{"path": name, "text": html if name == "index.html" else
                (restored / name).read_text() if (restored / name).is_file() else
                ("{}" if name.endswith(".json") else "Retained local technical design evidence.")}
                for name in file_names], "fonts": []}
            request = {"project_dir": ".", "sources": [{"path": item["path"]} for item in frozen["constraints"]["sources"]],
                "text_layers": frozen["constraints"]["text_layers"], "protected_regions": frozen["constraints"]["protected_regions"]}
            concept_path = restored / "reference/composition-reference.png"
            self.assertTrue(concept_path.is_file(), "Original nonshipping concept in sealed bundle required")
            concept = concept_path.read_bytes()
            font_files = [path for path in (restored / "assets").rglob("*")
                if path.is_file() and path.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf"}]
            report_user = "dual-private-report-owner"
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                (report_user, report_user, report_user + "@example.invalid", "fixture", "fixture", fixture.now.isoformat()))
            states, by_user = {}, {}
            for index, user in enumerate((fixture.user, fixture.other)):
                report = str(uuid.uuid4())
                db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)",
                    (report, user, approved[0], "美食", "{}", fixture.now.isoformat()))
                refs = [storage.store_media_bytes(user, purpose="image", content_type=("image/png" if body.startswith(b"\x89PNG") else "image/webp" if body.startswith(b"RIFF") else "image/jpeg"), payload=body,
                    item_count=1, ttl_seconds=86400) for body in raw_sources]
                policy = {**fixture.policy, "budget_id": jobs.FORMAL_BUDGET_ID, "design_version": 3,
                    "max_physical_calls": None, "workflow_engine": "editable_design_opencode_v1",
                    "design_model": provider.MODEL}
                report_input = {"title": approved[0], "body": "Controlled resource replay using sealed actual photographs.",
                    "title_variants": approved[1:], "approved_titles": approved}
                result = fixture.submit(key="dual-sdk-" + str(index), user_id=user, report_id=report,
                    source_refs=[ref.id for ref in refs], input_snapshot=report_input, policy_snapshot=policy,
                    quote_version=jobs.policy_quote_version(policy))
                state = {"job": result["job_id"], "user": user, "turns": 0, "bridge": None,
                    "source_hashes": {ref.content_sha256 for ref in refs}, "wire_count": 0, "render": None,
                    "assertions": [], "report": report, "refs": [ref.id for ref in refs], "policy": policy,
                    "report_input": report_input}
                states[state["job"]] = state
                by_user[user] = state
            raw_source_bytes = sum(len(body) for body in raw_sources)
            del raw_sources, original_bundle
            gc.collect()
            # Exact real getters; no startup, network download or empty warm.
            stage[0] = "warm_once"
            api = importlib.import_module("api")
            with mock.patch.object(api, "_model_artifacts_ensured", True), mock.patch.object(api,
                    "ensure_model_artifacts", side_effect=AssertionError("No model acquisition")):
                models = [api.get_v04_composite_model(), api.get_v04_ready_classifier(), api.get_v04_preference_ranker()]
            self.assertTrue(all(value is not None for value in models))
            model_pins = {name: file_pin(getattr(api, name)[0]) for name in
                ("_v04_model_signature", "_v04_ready_classifier_signature", "_v04_preference_ranker_signature")}
            points["warm_fixture_before_sessions"] = sampled_point()
            stage[0] = "two_actual_sessions"
            first_entered = threading.Event()
            def both_first_requests():
                with lock:
                    self.assertEqual(len(host_rows), 2)
                    self.assertTrue(all(row["process"].poll() is None for row in host_rows))
                points["two_live_hosts_at_first_model_requests"] = sampled_point()
                first_entered.set()
            first_barrier = threading.Barrier(2, action=both_first_requests, timeout=90)
            def candidate_action():
                points["two_actual_candidates_retained"] = sampled_point()
                self.assertEqual(len(resident), 2)
            candidate_barrier = threading.Barrier(2, action=candidate_action, timeout=180)
            class Witness(runtime.Bridge):
                def __init__(inner, **kwargs):
                    super().__init__(**kwargs)
                    state = states[inner.job_id]
                    state["bridge"] = inner
                    # Restore only trusted licensed font assets. Source photos
                    # still come from run_cover's actual materialization.
                    for path in font_files:
                        target = inner.directory / path.relative_to(restored)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
            def transport_for(state):
                def transport(http_request):
                    try:
                        payload = json.loads(http_request.content)
                        state["turns"] += 1
                        state["wire_count"] += 1
                        turn, bridge = state["turns"], state["bridge"]
                        if turn == 1:
                            self.assertEqual(len(runtime._images_in(payload)), 9)
                            self.assertEqual(set(bridge.inspection_previews), state["source_hashes"])
                            self.assertEqual(runtime._images_in(payload),
                                {item["sha256"] for item in bridge.inspection_previews.values()})
                            first_barrier.wait()
                            calls = [("cover_seedream", {"prompt": "Controlled nonshipping composition from the same original photographs."})]
                        elif turn == 2:
                            self.assertEqual(set(bridge.inspected_sources), state["source_hashes"])
                            calls = [("cover_view", {"path": "reference/composition-reference.png"})]
                        elif turn == 3:
                            self.assertIn(digest(concept), runtime._images_in(payload))
                            calls = [("cover_render", {"request": request, "prepare": packet})]
                        elif turn == 4:
                            value = compound.fixtures.fixture.returned_value(payload, "render", tool_call_id="dual_3_0")
                            self.assertTrue(value["render"]["ok"], str(value["render"].get("code")))
                            state["render"] = value["render"]
                            calls = [("cover_view", {"path": state["render"]["image_path"]})]
                        elif turn == 5:
                            self.assertTrue({state["render"]["png_sha256"], state["render"]["thumbnail_sha256"]}.issubset(runtime._images_in(payload)))
                            calls = [("cover_write", {"path": "render-review.md", "text": "Controlled actual final and thumbnail pixels received. Mock aesthetic response, not merchant acceptance."})]
                        elif turn == 6:
                            return httpx.Response(200, json=model_reply(turn, text="Controlled local design complete."))
                        else:
                            self.assertEqual(turn, 7)
                            self.assertTrue(set(bridge.inspected_sources) == state["source_hashes"])
                            qc = {"approved": True, "text_matches": True, "facts_preserved": True,
                                "subject_preserved": True, "issues": [], "local_adjustment": None,
                                "design_checks": {key: True for key in ("main_visual", "message_focus", "typographic_hierarchy",
                                    "layout_balance", "thumbnail_legibility", "style_fits_subject")}}
                            return httpx.Response(200, json=model_reply(turn, text=json.dumps(qc)))
                        return httpx.Response(200, json=model_reply(turn, calls))
                    except AssertionError as error:
                        state["assertions"].append(str(error))
                        raise
                return httpx.MockTransport(transport)
            def image_transport_for(state):
                def transport(request_wire):
                    value = json.loads(request_wire.content)
                    images = value["image"] if isinstance(value["image"], list) else [value["image"]]
                    self.assertEqual({digest(base64.b64decode(item.split(",", 1)[1])) for item in images}, state["source_hashes"])
                    return httpx.Response(200, json={"model": runtime.cover_seedream.MODEL,
                        "data": [{"size": "1776x2368", "b64_json": base64.b64encode(concept).decode()}],
                        "usage": {"input_images": 9, "generated_images": 1}})
                return httpx.MockTransport(transport)
            original_agent = runtime.run_cover
            def actual_runtime(**kwargs):
                state = states[kwargs["job_id"]]
                local.job = state["job"]
                state["raw_resident_bytes"] = sum(len(source["payload"]) for source in kwargs["sources"])
                result = original_agent(**kwargs, model_transport=transport_for(state),
                    image_transport=image_transport_for(state), bridge_class=Witness)
                with lock:
                    resident[state["job"]] = {"raw_bytes": state["raw_resident_bytes"],
                        "encoded_bundle_bytes": len(result.artifact["editable_bundle"]),
                        "final_png_bytes": len(result.final_bytes)}
                candidate_barrier.wait()
                return result
            original_popen, original_stop = subprocess.Popen, runtime._stop_host
            def observe_popen(args, *pos, **kwargs):
                process = original_popen(args, *pos, **kwargs)
                if any(str(arg).endswith("cover_agent_host/worker.mjs") for arg in args):
                    with lock:
                        host_rows.append({"pid": process.pid, "job": getattr(local, "job", None),
                            "started": time.monotonic(), "ended": None, "process": process})
                return process
            def observe_stop(process):
                try:
                    return original_stop(process)
                finally:
                    with lock:
                        for row in host_rows:
                            if row["pid"] == process.pid and row["ended"] is None:
                                row["ended"] = time.monotonic()
            original_slot = artifacts.render_slot
            @contextmanager
            def observe_slot(**kwargs):
                requested = time.monotonic()
                with original_slot(**kwargs):
                    with lock:
                        renderer["active"] += 1
                        renderer["peak"] = max(renderer["peak"], renderer["active"])
                        render_rows.append({"job": getattr(local, "job", None),
                            "wait_seconds": time.monotonic() - requested})
                    try:
                        yield
                    finally:
                        with lock:
                            renderer["active"] -= 1
            stack.enter_context(mock.patch.object(runtime.subprocess, "Popen", side_effect=observe_popen))
            stack.enter_context(mock.patch.object(runtime, "_stop_host", side_effect=observe_stop))
            stack.enter_context(mock.patch.object(artifacts, "render_slot", side_effect=observe_slot))
            stack.enter_context(mock.patch.object(cover_runtime, "run_cover", side_effect=actual_runtime))
            worker = service.CoverWorker()
            self.assertEqual(worker.slots, 2)
            worker.start()
            self.assertEqual(len(worker.tasks), 2)
            self.assertEqual(worker.executor._max_workers, 3)
            try:
                deadline = time.monotonic() + 240
                report_permit = False
                while not all(jobs.get_job(state["user"], state["job"])["status"] in
                        {"completed", "failed", "outcome_unknown"} for state in states.values()):
                    self.assertLess(time.monotonic(), deadline, "Controlled two-session lifecycle did not terminate")
                    if first_entered.is_set() and not report_permit:
                        # One real unrelated report admission while two cover
                        # sessions exist. This is scheduler proof, not a report.
                        def report_admission():
                            operation, owns = manager.register("dual-private-report-owner", str(uuid.uuid4()), route="/generate")
                            self.assertTrue(owns)
                            inv = public.Invocation(operation.user_id, "dual-report", route="/generate")
                            inv.admission_state = operation
                            token = public._invocation.set(inv)
                            try:
                                with public.model_admission_sync(str(uuid.uuid4()), "doubao", model_id="doubao-seed-2-0-lite-260428"):
                                    return True
                            finally:
                                public._invocation.reset(token)
                                manager.finish(operation)
                        report_permit = await asyncio.to_thread(report_admission)
                    await asyncio.sleep(.05)
                for state in states.values():
                    job = jobs.get_job(state["user"], state["job"])
                    self.assertEqual(job["status"], "completed", json.dumps({"failure": job["failure_code"], "assertions": state["assertions"]}))
                    self.assertEqual(state["wire_count"], 7)
                await worker.stop()
            finally:
                first_barrier.abort()
                candidate_barrier.abort()
                await worker.stop()
            self.assertTrue(all(task.done() for task in worker.tasks))
            self.assertTrue(worker.maintenance_task.done())
            self.assertEqual(len(host_rows), 2)
            self.assertEqual({row["job"] for row in host_rows}, set(states))
            self.assertTrue(all(row["ended"] is not None and row["process"].poll() is not None for row in host_rows))
            self.assertLess(max(row["started"] for row in host_rows), min(row["ended"] for row in host_rows))
            self.assertEqual(renderer["peak"], 1)
            self.assertTrue(report_permit)
            points["after_two_saved"] = sampled_point()
            for state in states.values():
                row = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (state["job"],)))
                self.assertEqual((row["complete_applied"], row["refund_applied"], float(row["credits_used"])), (1, 0, 8))
                # Same-key normal submit remains the original job, not a charge.
                repeated = fixture.submit(key="dual-sdk-" + str(list(states).index(state["job"])),
                    user_id=state["user"], report_id=state["report"], source_refs=state["refs"],
                    input_snapshot=state["report_input"], policy_snapshot=state["policy"],
                    quote_version=jobs.policy_quote_version(state["policy"]))
                self.assertEqual(repeated["job_id"], state["job"])
                self.assertFalse(repeated["created"])
                stage[0] = "saved_restore_free_edit"
                def edit_saved():
                    local.job = state["job"]
                    before_job = jobs.get_job(state["user"], state["job"])
                    layer = next(item for item in before_job["layout"]["text_layers"] if item["id"] == "label-bread")
                    text = layer["text"].replace("·", "") if "·" in layer["text"] else layer["text"].replace("九篮", "九篮·", 1)
                    if text == layer["text"]:
                        text = layer["text"] + " "
                    operation, owns = manager.register(state["user"], str(uuid.uuid4()), route="/covers/adjust")
                    self.assertTrue(owns)
                    inv = public.Invocation(state["user"], "dual-free-edit", route="/covers/adjust")
                    inv.admission_state = operation
                    token = public._invocation.set(inv)
                    try:
                        updated = service.adjust(state["user"], state["job"], text=text,
                            position=None, layer_id=layer["id"], expected_revision=before_job["asset_revision"])
                        ref = jobs.asset_reference(state["user"], state["job"])
                        _, png = storage.load_media_bytes(ref, user_id=state["user"], purpose="image")
                        self.assertEqual(updated["asset_revision"], 2)
                        self.assertTrue(png.startswith(b"\x89PNG"))
                        return {"png_bytes": len(png), "sha256": digest(png)}
                    finally:
                        public._invocation.reset(token)
                        manager.finish(operation)
                state["free_edit"] = await asyncio.to_thread(edit_saved)
                after_row = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (state["job"],)))
                self.assertEqual((after_row["complete_applied"], after_row["refund_applied"], after_row["credits_used"]),
                    (row["complete_applied"], row["refund_applied"], row["credits_used"]))
            points["after_saved_free_edits"] = sampled_point()
            # One sequential local UNKNOWN through Base.model, without a third
            # SDK process or another supplier. No old request is replayed.
            first = next(iter(states.values()))
            unknown_task = fixture.submit(key="dual-known-local-unknown", user_id=first["user"],
                report_id=first["report"], source_refs=first["refs"], input_snapshot=first["report_input"],
                policy_snapshot=first["policy"], quote_version=jobs.policy_quote_version(first["policy"]))
            unknown_http = []
            def unknown_transport(request_wire):
                unknown_http.append(1)
                raise httpx.ReadTimeout("Controlled one-shot UNKNOWN; no real supplier", request=request_wire)
            def unknown_runtime(**kwargs):
                directory = runtime.workspace_root() / kwargs["job_id"]
                directory.mkdir()
                bridge = runtime.Bridge(job_id=kwargs["job_id"], directory=directory,
                    sources=kwargs["sources"], hooks=kwargs["hooks"], model_transport=httpx.MockTransport(unknown_transport))
                bridge.request_deadline = time.time() + 900
                bridge.model({"model": provider.MODEL, "messages": [{"role": "user", "content": "Controlled UNKNOWN"}],
                    "max_completion_tokens": 1024, "stream": False})
                self.fail("UNKNOWN transport cannot return success")
            stage[0] = "sequential_mock_UNKNOWN_no_SDK"
            await asyncio.to_thread(service.run_next, runtime=unknown_runtime)
            unknown = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (unknown_task["job_id"],)))
            self.assertEqual((unknown["complete_applied"], unknown["refund_applied"]), (0, 0))
            self.assertEqual(float(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (unknown["usage_id"],))[0]), 0)
            self.assertEqual(unknown_http, [1])
            self.assertIsNone(await asyncio.to_thread(service.run_next, runtime=unknown_runtime))
            self.assertEqual(unknown_http, [1], "Query/recovery cannot replay UNKNOWN")
            expiry = datetime.fromisoformat(unknown["lease_expires_at"]) + timedelta(seconds=1)
            jobs.release_expired_unknowns(now=expiry)
            jobs.release_expired_unknowns(now=expiry)
            unknown = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (unknown_task["job_id"],)))
            self.assertEqual((unknown["complete_applied"], unknown["refund_applied"]), (0, 1))
            self.assertEqual(float(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (unknown["usage_id"],))[0]), 0)
            for state in states.values():
                saved = dict(db.fetchone("SELECT complete_applied,refund_applied,usage_id FROM idempotency_requests WHERE id=?", (state["job"],)))
                self.assertEqual((saved["complete_applied"], saved["refund_applied"]), (1, 0))
                self.assertEqual(float(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (saved["usage_id"],))[0]), 8)
            self.assertEqual(len(host_rows), 2, "The sequential UNKNOWN cannot start a third SDK")
            sample_stop.set()
            sampler.join(5)
            self.assertFalse(sampler.is_alive())
            self.assertFalse(sample_errors)
            self.assertTrue(samples)
            self.assertLessEqual(max(item["media_active"] for item in samples), 2)
            self.assertEqual(max(item["renderer_active"] for item in samples), 1)
            self.assertTrue(all(item["buffers_active_bytes"] <= 256 * 1024 ** 2 for item in samples))
            for queue in (manager.calls, manager.media, manager.buffers):
                with queue.lock:
                    self.assertFalse(queue.active)
                    self.assertFalse(queue._tickets())
            self.assertFalse(manager.operations)
            after = resources(root / "workspaces")
            all_owned_processes_gone = None
            if strict_profile:
                # The original private runner has exactly init+this Python,
                # no shell/health process. Chromium may have been reparented to
                # init, so checking only the two host PIDs is insufficient.
                end = time.monotonic() + 5
                while sum(value for key, value in after["process_states"].items() if key not in {"Z", "X"}) > 2 and time.monotonic() < end:
                    await asyncio.sleep(.1)
                    after = resources(root / "workspaces")
                self.assertEqual(sum(value for key, value in after["process_states"].items() if key not in {"Z", "X"}), 2)
                all_owned_processes_gone = True
            if after["actual_linux_cgroup"]:
                self.assertEqual(after["memory_events"]["oom"] - before["memory_events"]["oom"], 0)
                self.assertEqual(after["memory_events"]["oom_kill"] - before["memory_events"]["oom_kill"], 0)
                self.assertEqual(after["pids_events"]["max"] - before["pids_events"]["max"], 0)
            proof = {"state": "CONTROLLED_TWO_REAL_SDK_LIFECYCLES_PASS", "fixture_kind": kind,
                "fixture_pin": tar_pin, "real_supplier_calls": 0, "production_DB_calls": 0,
                "private_SQLite_accounting": True, "node_version": node_version, "model_warm_once": model_pins,
                "tested_source_pins": tested_source_pins, "object_backend_fs": object_fs,
                "workspace_fs": after["workspace_fs"], "browser_tmp_fs": after["browser_tmp_fs"],
                "strict_production_profile_checked": strict_profile,
                "production_profile_equivalent": production_profile_equivalent,
                "capacity_acceptance_eligible": production_profile_equivalent and kind == "authorized_R18_actual_fixture",
                "two_distinct_SDK_PIDs_overlap": True, "actual_SDK_count": 2,
                "actual_CoverWorker_slots": worker.slots, "actual_worker_loop_tasks": len(worker.tasks),
                "dedicated_executor_max_workers": worker.executor._max_workers,
                "all_worker_and_maintenance_tasks_finished": True,
                "first_known200_previews_per_session": 9, "renderer_peak": renderer["peak"],
                "media_peak": max(item["media_active"] for item in samples), "remote_capacity": manager.calls.capacity,
                "unrelated_report_admission_progressed": report_permit, "report_full_workflow_proved": False,
                "raw_originals_per_task_bytes": raw_source_bytes, "actual_candidates_retained": resident,
                "saved_free_edit_per_task": [state["free_edit"] for state in states.values()],
                "unique_8_credits_each_only_in_private_fixture": True,
                "one_sequential_UNKNOWN_zero_used_released_once": True,
                "all_hosts_joined_and_all_tickets_released": True,
                "strict_container_all_owned_processes_gone": all_owned_processes_gone, "sampler_joined": True,
                "before": before, "after": after, "stage_points": points,
                "sample_count": len(samples), "memory_peak_bytes": after.get("memory_peak_bytes"),
                "sampled_memory_current_peak": max(item.get("memory_current_bytes", 0) for item in samples),
                "sampled_pids_peak": max(item.get("pids_current", 0) for item in samples),
                "workspace_available_min": min(item["workspace_fs"]["available_bytes"] for item in samples),
                "browser_tmp_available_min": min(item["browser_tmp_fs"]["available_bytes"] for item in samples),
                "merchant_quality_acceptance": False, "real_vendor_throughput_proved": False,
                "ten_or_100_real_users_proved": False}
            print("COVER_DUAL_SDK_CAPACITY_PROOF=" + json.dumps(proof, sort_keys=True))
