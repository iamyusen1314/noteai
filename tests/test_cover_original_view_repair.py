"""Local pre-dispatch repair; no external model or production database is used."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_provider as provider
import cover_agent_runtime as runtime
import cover_runtime


def returned_value(body, field):
    """Find a field in actual SDK tool content, including its nested JSON text."""
    def find(value):
        if isinstance(value, str):
            try:
                return find(json.loads(value))
            except (ValueError, TypeError):
                return None
        if isinstance(value, dict):
            if field in value:
                return value
            value = list(value.values())
        if isinstance(value, list):
            for item in reversed(value):
                found = find(item)
                if found is not None:
                    return found
        return None
    for message in reversed(body["messages"]):
        if message["role"] == "tool":
            found = find(message.get("content"))
            if found is not None:
                return found
    raise AssertionError("SDK did not expose expected tool field: " + field)


def png(index, *, rolling=False):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    if rolling:
        # A valid private ancillary chunk exercises the real 25/15 MiB
        # encoded-byte rolling budget without large decoded fixture images.
        metadata.add(b"npAD", b"p" * 2250000)
    Image.new("RGB", (320, 240), (20 * index, 100, 200 - index)).save(output, "PNG", pnginfo=metadata)
    return output.getvalue()


def sources(directory, count=9, *, rolling=False):
    (directory / "assets").mkdir()
    result = []
    for index in range(count):
        payload = png(index, rolling=rolling)
        name = "assets/source-" + str(index + 1) + ".png"
        (directory / name).write_bytes(payload)
        result.append({"media_ref": "original-" + str(index + 1), "path": name,
            "payload": payload, "sha256": hashlib.sha256(payload).hexdigest()})
    return result


def response(turn, calls=None):
    message = {"role": "assistant", "content": None if calls else "Offline inspection fixture complete."}
    if calls:
        message["tool_calls"] = [{"id": "repair_" + str(turn) + "_" + str(index),
            "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
            for index, (name, arguments) in enumerate(calls)]
    return {"id": "chatcmpl-local-repair-" + str(turn), "object": "chat.completion", "created": 1,
        "model": provider.MODEL, "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


class OriginalViewRepairTests(unittest.TestCase):
    def test_view_batches_bound_encoded_bytes_preserve_order_and_never_resize(self):
        fixture = [{"path": "assets/" + str(index), "payload": b"x" * size}
            for index, size in enumerate((27, 27, 57, 100, 3))]
        originals = [item["payload"] for item in fixture]
        with mock.patch.object(runtime, "_VIEW_BATCH_ENCODED_LIMIT", 100):
            self.assertEqual(runtime._original_view_batches(fixture),
                [["assets/0"], ["assets/1"], ["assets/2"], ["assets/3"], ["assets/4"]])
            self.assertEqual(runtime._original_view_batches(fixture[:1] + fixture[-1:]),
                [["assets/0", "assets/4"]])
        self.assertEqual([item["payload"] for item in fixture], originals)
        self.assertEqual(runtime._original_view_batches([]), [])
        self.assertEqual(runtime._VIEW_BATCH_ENCODED_LIMIT, 15 * 1024 * 1024)

    def test_missing_feedback_is_bounded_and_never_dispatches_or_marks_seen(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = sources(Path(root))
            hooks = mock.Mock()
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=fixture, hooks=hooks)
            with mock.patch.object(runtime.cover_seedream, "generate_background") as image:
                for attempt in (1, 2):
                    result = bridge.tool({"name": "cover_seedream", "arguments": {"prompt": "fixture"}})
                    self.assertEqual(result["repair_attempt"], attempt)
                    self.assertEqual((result["code"], result["recoverable"], result["dispatched"], result["repair_limit"]),
                        ("COVER_AGENT_ORIGINALS_NOT_VIEWED", True, False, 2))
                    self.assertEqual(result["missing_originals"], [{"ref": item["media_ref"], "path": item["path"],
                        "sha256": item["sha256"]} for item in fixture])
                    self.assertEqual(result["view_batches"], [[item["path"] for item in fixture]])
                    self.assertEqual(bridge.seen_images, set())
                with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_ORIGINALS_NOT_VIEWED"):
                    bridge.tool({"name": "cover_seedream", "arguments": {"prompt": "fixture"}})
            image.assert_not_called()
            hooks.on_stage.assert_not_called()
            hooks.before_call.assert_not_called()
            self.assertEqual(bridge.costs, [])

    def test_unknown_model_result_does_not_mark_original_seen(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = sources(Path(root), 1)
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=fixture, hooks=mock.Mock())
            bridge.request_deadline = time.time() + 500
            body = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(fixture[0]["payload"]).decode()}}]}]}
            with mock.patch.object(runtime.public_product, "assert_result_known"), \
                    mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                    mock.patch.object(provider, "complete", side_effect=provider.CoverAgentProviderError("SUPPLIER_RESULT_UNKNOWN")):
                with self.assertRaisesRegex(provider.CoverAgentProviderError, "SUPPLIER_RESULT_UNKNOWN"):
                    bridge.model(body)
            self.assertEqual(bridge.seen_images, set())
            self.assertEqual(bridge.costs, [])

    @unittest.skipUnless(shutil.which("node"), "Node required for actual host callback regression")
    def test_host_only_resets_exact_known_predispatch_rejection(self):
        # Execute the actual production callback and validator, rather than a
        # second implementation of the once/UNKNOWN state transition.
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const validator = source.slice(source.indexOf('function recoverableOriginalViewRejection('), source.indexOf('const send ='));
const callback = source.slice(source.indexOf("    tool('cover_seedream',"), source.indexOf("    tool('cover_render',")).trim().replace(/,$/, '');
async function attempt(result, unknown=false, before={}) {
  const checkpoint = {...before}, writes = [], ctx = vm.createContext({checkpoint,
    checkpointPath: '/unused', job: {images:[{name:'r1',path:'assets/1.png'}]},
    sha: ()=>'promptsha', error: code=>Object.assign(new Error(code),{code}),
    atomicJSON: async (_path,value)=>writes.push(JSON.parse(JSON.stringify(value))),
    bridge: async ()=>({result,unknown}), objectSchema: x=>x,
    tool: (_n,_d,_i,execute)=>execute});
  vm.runInContext(validator + '\nglobalThis.execute=' + callback, ctx);
  let errorCode; try { await ctx.execute({prompt:'fixture'}); } catch(e) { errorCode=e.code; }
  return {checkpoint,writes,errorCode,ctx};
}
(async ()=>{
 const valid={ok:false,code:'COVER_AGENT_ORIGINALS_NOT_VIEWED',recoverable:true,dispatched:false,
   required_action:'cover_view',repair_limit:2,repair_attempt:1,missing_originals:[{ref:'r1',path:'assets/1.png',sha256:'a'.repeat(64)}]};
 const fixed=await attempt(valid); assert.equal(fixed.errorCode,undefined); assert.equal(fixed.checkpoint.concept_requested,false);
 assert.equal(fixed.checkpoint.pending_tool,null); assert.equal(fixed.checkpoint.original_view_repairs,1); assert.equal(fixed.writes.length,2);
 const second=await attempt({...valid,repair_attempt:2},false,{original_view_repairs:1}); assert.equal(second.checkpoint.concept_requested,false);
 const success=await attempt({path:'reference/composition-reference.png',sha256:'b'.repeat(64)});
 assert.equal(success.checkpoint.concept_requested,true); assert.equal(success.checkpoint.pending_tool,null);
 await assert.rejects(success.ctx.execute({prompt:'again'}),e=>e.code==='CONCEPT_ALREADY_REQUESTED');
 for(const [result,unknown,before,code] of [
   [valid,true,{},'SUPPLIER_RESULT_UNKNOWN'],
   [{...valid,dispatched:true},false,{},'ORIGINAL_VIEW_REPAIR_INVALID'],
   [{...valid,missing_originals:[{ref:'other',path:'assets/1.png'}]},false,{},'ORIGINAL_VIEW_REPAIR_INVALID'],
   [{...valid,repair_attempt:2},false,{},'ORIGINAL_VIEW_REPAIR_INVALID'],
   [valid,false,{original_view_repairs:2},'ORIGINAL_VIEW_REPAIR_INVALID']]) {
   const rejected=await attempt(result,unknown,before); assert.equal(rejected.errorCode,code);
   assert.equal(rejected.checkpoint.concept_requested,true); assert.equal(rejected.checkpoint.pending_tool.name,'cover_seedream');
 }
 const supplier=await attempt({ok:false,code:'SUPPLIER_FAILED'}); assert.equal(supplier.checkpoint.concept_requested,true);
 console.log(JSON.stringify({actual_host_callback:true,known_repair_limit:2,unknown_and_duplicate_do_not_reset:true}));
})().catch(e=>{console.error(e);process.exit(1)});
"""
        run = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script,
            str(runtime.ROOT / "cover_agent_host/host.mjs")], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["unknown_and_duplicate_do_not_reset"])


@unittest.skipUnless(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") and shutil.which("node"),
    "Explicit approved local SDK installation required")
class OriginalViewRepairSDKTests(unittest.TestCase):
    def test_actual_sdk_returned_batches_reduce_missing_view_rounds_without_weakening_seen_gate(self):
        from tests import test_cover_agent_provider as provider_fixture
        proofs = []
        for mode in ("sequential", "batch"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root, contextlib.ExitStack() as stack:
                directory = Path(root)
                manifest = os.environ.get("NOTEAI_COVER_REAL_NINE_MANIFEST")
                if manifest:
                    (directory / "assets").mkdir()
                    fixture = []
                    for index, item in enumerate(json.loads(Path(manifest).read_text())["files"]):
                        payload = Path(item["path"]).read_bytes()
                        self.assertEqual((len(payload), hashlib.sha256(payload).hexdigest()),
                            (item["bytes"], item["sha256"]))
                        name = "assets/source-" + str(index + 1) + ".jpg"
                        (directory / name).write_bytes(payload)
                        fixture.append({"media_ref": item["media_ref"], "path": name,
                            "payload": payload, "sha256": item["sha256"]})
                else:
                    fixture = sources(directory, rolling=True)
                self.assertEqual(len(fixture), 9)
                ledger = provider_fixture.CoverAgentProviderTests()
                ledger.setUp()
                stack.callback(ledger.tearDown)
                stack.enter_context(ledger.editable_claim())
                received, selected, rejections = [], [], []

                def known_response(turn, calls=None):
                    body = response(turn, calls)
                    body["usage"] = ledger.response()["usage"]
                    return httpx.Response(200, json=body)

                def model_transport(request):
                    prepared = json.loads(request.content)
                    hashes = runtime._images_in(prepared)
                    received.append(hashes)
                    missing = [item for item in fixture if item["sha256"] not in bridge.seen_images | hashes]
                    turn = len(received)
                    if turn == 1:
                        self.assertEqual(len(hashes), 5)
                        calls = [("cover_seedream", {"prompt": "Offline missing-originals contract only."})]
                    elif not missing:
                        return known_response(turn)
                    else:
                        if turn == 2:
                            rejection = returned_value(prepared, "missing_originals")
                            self.assertIs(rejection["dispatched"], False)
                            self.assertEqual(rejection["view_batches"], [[item["path"] for item in missing]])
                            rejections.append(rejection)
                        paths = [item["path"] for item in missing]
                        batch = paths[:1] if mode == "sequential" else rejections[0]["view_batches"][0]
                        selected.extend(batch)
                        calls = [("cover_view", {"path": value}) for value in batch]
                    return known_response(turn, calls)

                def before(stage, call_id, _estimate):
                    provider_fixture.cover_jobs.before_text_call(ledger.claim, stage, call_id)

                bridge = runtime.Bridge(job_id=ledger.claim["request_id"], directory=directory,
                    sources=fixture, hooks=cover_runtime.RuntimeHooks(before, lambda _record: None),
                    model_transport=httpx.MockTransport(model_transport))

                prompt = runtime._prompt({"title": "原照批量查看技术夹具", "body": "仅离线合同验证", "title_variants": []},
                    [{key: value for key, value in item.items() if key != "payload"} for item in fixture])
                with mock.patch.object(runtime.cover_seedream, "generate_background") as image:
                    with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_DESIGN_INCOMPLETE"):
                        # Normal admission needs its unchanged 180s useful
                        # read plus 140s margin; the test normally takes <1min.
                        bridge.run(prompt, deadline=time.time() + 600)
                image.assert_not_called()
                self.assertEqual(bridge.seen_images, {item["sha256"] for item in fixture})
                self.assertEqual(len(selected), 4)
                self.assertEqual(len(set(selected)), 4)
                self.assertEqual(bridge.original_view_repairs, 1)
                state = json.loads((directory / "host-state/host-checkpoint.json").read_text())
                activity = runtime._local_tool_diagnostic(state["local_tool_activity"])
                self.assertEqual(activity["attempts"]["cover_view"], 4)
                self.assertEqual(activity["attempts"]["cover_seedream"], 1)
                self.assertEqual(activity["last_name"], "cover_view")
                self.assertEqual(activity["last_outcome"], "returned")
                calls = provider_fixture.db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=?",
                    (ledger.claim["charge"]["usage_id"],))
                self.assertEqual(len(calls), len(received))
                self.assertTrue(all(call["state"] == "responded" and call["http_status"] == 200 for call in calls))
                proofs.append({"mode": mode, "model_responses": len(received), "normal_known_200_ledger_calls": len(calls),
                    "wire_sha256": [sorted(value) for value in received], "originals_seen": len(bridge.seen_images),
                    "original_bytes": sum(len(item["payload"]) for item in fixture), "local_tools": activity})
        self.assertEqual([proof["model_responses"] for proof in proofs], [6, 3])
        print("BATCH_ORIGINAL_VIEW_SDK_PROOF=" + json.dumps({"actual_manifest": bool(os.environ.get("NOTEAI_COVER_REAL_NINE_MANIFEST")),
            "cases": proofs, "supplier_calls": 0, "business_DB_writes": 0}))

    def test_real_sdk_rolling_nine_view_repair_concept_once(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            fixture = sources(directory, rolling=True)
            hooks = mock.Mock()
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=directory, sources=fixture, hooks=hooks)
            received, feedback = [], []

            def model_complete(prepared, **_kwargs):
                hashes = runtime._images_in(prepared)
                received.append(hashes)
                turn = len(received)
                if turn == 1:
                    self.assertEqual(len(hashes), 5, "Must exercise the SDK's actual rolling image budget")
                    calls = [("cover_seedream", {"prompt": "Offline synthetic concept preserving exact source identity."})]
                elif turn == 2:
                    rejection = returned_value(prepared, "missing_originals")
                    feedback.append(rejection)
                    self.assertEqual(rejection["repair_attempt"], 1)
                    self.assertEqual(len(rejection["missing_originals"]), 4)
                    self.assertEqual(bridge.seen_images, received[0])
                    calls = [("cover_view", {"path": original["path"]}) for original in rejection["missing_originals"]]
                elif turn == 3:
                    self.assertEqual(bridge.seen_images | hashes, {item["sha256"] for item in fixture})
                    calls = [("cover_seedream", {"prompt": "Offline concept after all originals actually reached the model."})]
                elif turn == 4:
                    self.assertEqual(returned_value(prepared, "role")["role"], "design_concept_reference_only_not_shipping_photo")
                    calls = [("cover_seedream", {"prompt": "Duplicate must be blocked locally."})]
                elif turn == 5:
                    self.assertEqual(returned_value(prepared, "code")["code"], "CONCEPT_ALREADY_REQUESTED")
                    return response(turn)
                else:
                    self.fail("Unexpected model continuation")
                return response(turn, calls)

            def image_complete(**kwargs):
                self.assertEqual(bridge.seen_images, {item["sha256"] for item in fixture})
                self.assertEqual(kwargs["source_images"], [item["payload"] for item in fixture])
                return png(9), {"stage": "image", "status": "responded", "provider": "synthetic-fixture", "call_id": kwargs["call_id"]}

            context = {"title": "原照技术回归", "body": "仅离线流程验证", "title_variants": []}
            prompt = runtime._prompt(context, [{key:value for key,value in item.items() if key != "payload"} for item in fixture])
            with mock.patch.object(runtime.public_product, "assert_result_known"), \
                    mock.patch.object(runtime.public_product, "model_admission_sync", side_effect=lambda *_args: contextlib.nullcontext()), \
                    mock.patch.object(provider, "complete", side_effect=model_complete) as models, \
                    mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=image_complete) as image:
                # Deliberately stop before rendering: this fixture owns the
                # missing-view repair and once gate, not aesthetic acceptance.
                with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_DESIGN_INCOMPLETE"):
                    bridge.run(prompt, deadline=time.time() + 300)
            self.assertEqual(models.call_count, 5)
            self.assertEqual(image.call_count, 1)
            self.assertEqual(bridge.original_view_repairs, 1)
            self.assertEqual(bridge.seen_images, {item["sha256"] for item in fixture})
            checkpoint = json.loads((directory / "host-state/host-checkpoint.json").read_text())
            self.assertEqual(checkpoint["original_view_repairs"], 1)
            self.assertTrue(checkpoint["concept_requested"])
            self.assertIsNone(checkpoint["pending_tool"])
            self.assertEqual(feedback[0]["dispatched"], False)
            print("ORIGINAL_VIEW_REPAIR_SDK_PROOF=" + json.dumps({"originals": 9, "initial_payload_images": 5,
                "missing_views": 4, "successful_model_payloads": 5, "concept_stubs": 1,
                "real_provider_calls": 0, "all_nine_hashes_seen_via_model": True, "duplicate_blocked": True}))


if __name__ == "__main__":
    unittest.main()
