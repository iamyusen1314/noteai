"""Offline integration proof against the installed, real OpenCode 2.1.2 SDK.

NOTEAI_COVER_HOST_NODE_MODULES points to the task-local exact installation.
No remote model endpoint, credential, account, or product database is involved.
"""
import ast
import base64
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT / "model"))
from cover_agent_thinking import ThinkingState
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNQKJhAEmIY1TCqYfhqAACs2CAQru0W7wAAAABJRU5ErkJggg==")


def provider_admission():
    """Execute the actual pure validator, without importing DB/env/provider I/O."""
    names = {"MODEL", "MAX_INPUT_TOKENS", "MAX_OUTPUT_TOKENS", "_NAME", "_KEYS",
             "_INPUT_DIAGNOSTIC_KEYS", "CoverAgentProviderError", "validated_input_diagnostics",
             "_OUTPUT_DIAGNOSTIC_KEYS", "_OUTPUT_FINISH_REASONS", "validated_output_diagnostics",
             "_RESERVATION_DIAGNOSTIC_KEYS", "_RESERVATION_EXCEPTION_TYPES", "validated_reservation_diagnostics",
             "_measure_input", "_invalid", "_image_tokens", "_validate_and_measure_payload",
             "_check_request_size", "prepare_payload", "admit_payload"}
    source = PROJECT / "model/cover_agent_provider.py"
    tree = ast.parse(source.read_text(), filename=str(source))
    selected = [node for node in tree.body if (
        isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))]
    found = {node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else node.targets[0].id
             for node in selected}
    if found != names:
        raise AssertionError("Pure provider contract changed: " + repr(names ^ found))
    media_source = PROJECT / "model/ark_media.py"
    media_tree = ast.parse(media_source.read_text(), filename=str(media_source))
    media_nodes = [node for node in media_tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id in {"MAX_IMAGE_BYTES", "MAX_REQUEST_BYTES"}
                           for t in node.targets)]
    media = {}
    exec(compile(ast.Module(body=media_nodes, type_ignores=[]), str(media_source), "exec"), media)
    namespace = {"base64": base64, "deepcopy": deepcopy, "io": io, "json": json,
                 "math": math, "re": re, "Image": Image,
                 "ark_media": SimpleNamespace(**{key: media[key] for key in ("MAX_IMAGE_BYTES", "MAX_REQUEST_BYTES")}),
                 "public_product": SimpleNamespace(TrialProviderStopped=RuntimeError)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def text_values(value):
    if isinstance(value, str):
        return [] if value.startswith("data:image/") else [value]
    if isinstance(value, list):
        return [text for item in value for text in text_values(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in text_values(item)]
    return []


def image_hashes(body):
    return [hashlib.sha256(base64.b64decode(part["image_url"]["url"].split(",", 1)[1])).hexdigest()
            for message in body["messages"] if isinstance(message.get("content"), list)
            for part in message["content"] if part.get("type") == "image_url"]


class HostProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES")
        cls.node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not cls.modules or not cls.node:
            raise unittest.SkipTest("Explicit task-local OpenCode installation and node required")
        cls.node_version = subprocess.run([cls.node, "--version"], capture_output=True,
                                          text=True, check=True, timeout=5).stdout.strip()
        cls.root = Path(tempfile.mkdtemp(prefix="noteai-cover-host-proof-"))
        cls.receipts = []

    @classmethod
    def tearDownClass(cls):
        receipt = {"real_model_requests": 0, "sdk_version": "2.1.2", "node_version": cls.node_version,
                   "fixtures": cls.receipts}
        (cls.root / "proof-results.json").write_text(json.dumps(receipt, indent=2))
        output = os.environ.get("NOTEAI_COVER_HOST_PROOF_OUTPUT")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            shutil.copytree(cls.root, Path(output) / cls.root.name)
        print("HOST_PROOF_EVIDENCE=" + str(cls.root))

    def request(self, case, *, mode="run", limit=None, behavior="success", session_id=None,
                forbidden_path=None, admission=None, respond=None, nine_photos=False, thinking=None):
        root = self.root / case
        (root / "work").mkdir(parents=True, exist_ok=True)
        (root / "work/photo.png").write_bytes(PNG)
        photos = [{"path": "photo.png"}]
        if nine_photos:
            photos = []
            for index in range(1, 10):
                target = root / ("work/source-" + str(index) + ".png")
                image = Image.new("RGB", (32, 32), (index * 23, index * 17, index * 11))
                image.save(target)
                photos.append({"path": target.name, "name": "original-" + str(index)})
        prompt = "Offline proof only. Follow the returned tool calls and finish. Do not generate artwork."
        if nine_photos:
            prompt += "\n批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。\n原照索引=" + json.dumps([
                {"path": photo["path"], "sha256": hashlib.sha256((root / "work" / photo["path"]).read_bytes()).hexdigest()}
                for photo in photos], ensure_ascii=False)
        start = {
            "type": "start", "job_id": case, "state_dir": str(root / "state"),
            "work_dir": str(root / "work"),
            "skill_dir": str(PROJECT / "model/cover_editable/vendor/editable-design"),
            "editable_cli": str(PROJECT / "model/cover_editable/cli.mjs"),
            "model_id": admission["MODEL"] if admission else "offline-fixture", "prompt": prompt,
            "images": photos, "max_model_requests": limit,
            "deadline_epoch_ms": int((time.time() + 60) * 1000), "mode": mode,
        }
        if session_id:
            start["session_id"] = session_id
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "NOTEAI_COVER_HOST_NODE_MODULES": self.modules}
        for key in ["EDITABLE_DESIGN_BROWSER", "PUPPETEER_EXECUTABLE_PATH", "NO_SANDBOX", "EDITABLE_DESIGN_NO_SANDBOX"]:
            if os.environ.get(key):
                env[key] = os.environ[key]
        proc = subprocess.Popen([self.node, str(HERE / "worker.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, bufsize=1)
        host_sha = hashlib.sha256((HERE / "host.mjs").read_bytes()).hexdigest()
        proc.stdin.write(json.dumps(start) + "\n"); proc.stdin.flush()
        events, calls, preflights, responses, supplier_bodies = [], [], [], [], []
        selector = selectors.DefaultSelector(); selector.register(proc.stdout, selectors.EVENT_READ)
        until = time.time() + 75
        try:
            while time.time() < until:
                if not selector.select(1):
                    if proc.poll() is not None:
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                event = json.loads(line); events.append(event)
                if event["type"] == "model_preflight":
                    self.assertEqual((event["method"], event["path"]), ("POST", "/chat/completions"))
                    wire = thinking.restore(event["body"]) if thinking is not None else event["body"]
                    outcome = admission["admit_payload"](wire) if admission else {"allowed": True}
                    preflights.append({"label": event.get("label"), "outcome": outcome,
                                       "measurement": admission["_validate_and_measure_payload"](wire)[1] if admission else None,
                                       "body_sha256": hashlib.sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest()})
                    answer = {"type": "model_preflight_response", "id": event["id"], **outcome}
                    proc.stdin.write(json.dumps(answer) + "\n"); proc.stdin.flush()
                if event["type"] == "model_request":
                    calls.append(event)
                    wire = thinking.restore(event["body"]) if thinking is not None else event["body"]
                    self.assertEqual(preflights[-1]["body_sha256"], hashlib.sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest())
                    supplier_bodies.append(wire)
                    if behavior == "disconnect":
                        proc.stdin.close()
                        continue
                    if respond:
                        answer = respond({**event, "body": wire}, calls)
                    elif behavior == "unknown":
                        answer = {"type": "model_response", "id": event["id"], "unknown": True}
                    elif behavior == "503":
                        answer = {"type": "model_response", "id": event["id"], "status": 503, "body": {"error": {"message": "controlled offline failure", "type": "server_error"}}}
                    else:
                        ordinal = len(calls)
                        if ordinal == 1 and forbidden_path:
                            fn, args = "cover_write", {"path": forbidden_path, "text": "{}"}
                        elif ordinal == 1 and behavior == "unsafe_html":
                            fn, args = "cover_write", {"path": "unsafe.html", "text": '<html><head></head><body><script>fetch("https://example.invalid")</script></body></html>'}
                        elif ordinal == 1:
                            fn, args = "cover_write", {"path": "evidence.md", "text": "offline tool execution"}
                        elif ordinal == 2:
                            fn, args = "cover_view", {"path": "photo.png"}
                        else:
                            fn, args = None, None
                        message = {"role": "assistant", "content": "OFFLINE_COMPLETE" if fn is None else None}
                        if fn:
                            message["tool_calls"] = [{"id": "call_" + str(ordinal), "type": "function", "function": {"name": fn, "arguments": json.dumps(args)}}]
                        body = {"id": "chatcmpl_fixture", "object": "chat.completion", "created": 1, "model": "offline-fixture", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if fn else "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
                        answer = {"type": "model_response", "id": event["id"], "status": 200, "body": body}
                    if thinking is not None and answer.get("status") == 200:
                        answer = {**answer, "body": thinking.remember(answer["body"])}
                    responses.append(answer)
                    proc.stdin.write(json.dumps(answer) + "\n"); proc.stdin.flush()
                if event["type"] == "result":
                    break
            if not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            stderr = proc.stderr.read()
            proc.stdout.close(); proc.stderr.close()
            selector.close()
        (root / (mode + "-" + behavior + "-events.json")).write_text(json.dumps(events, indent=2))
        (root / (mode + "-" + behavior + "-responses.json")).write_text(json.dumps(responses, indent=2))
        (root / (mode + "-" + behavior + "-synthetic-supplier-bodies.json")).write_text(json.dumps(supplier_bodies, indent=2))
        (root / (mode + "-" + behavior + "-stderr.txt")).write_text(stderr)
        result = next((event for event in reversed(events) if event["type"] == "result"), None)
        self.assertIsNotNone(result, stderr)
        self.receipts.append({"case": case, "mode": mode, "behavior": behavior,
                              "host_sha256": host_sha,
                              "model_bridge_requests": len(calls), "preflights": preflights,
                              "result": result, "events_file": str(root / (mode + "-" + behavior + "-events.json"))})
        return result, calls, events, root

    def test_complete_skill_image_tool_loop_and_reopen_without_dispatch(self):
        result, calls, events, root = self.request("success")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call["ordinal"] for call in calls], [1, 2, 3])
        self.assertTrue(all(call["body"]["stream"] is False for call in calls))
        first = json.dumps(calls[0]["body"])
        self.assertTrue("Create an art-directed composition reference" in first, "Full Skill body missing")
        self.assertTrue("## Read the render" in first and "## Deliver" in first, "Full Skill final phases missing")
        self.assertTrue(base64.b64encode(PNG).decode() in first, "Photo pixels did not reach transport")
        tool_names = {tool["function"]["name"] for tool in calls[0]["body"]["tools"]}
        self.assertEqual(tool_names, {"cover_read", "cover_write", "cover_view", "cover_seedream", "cover_render", "cover_check"})
        self.assertEqual((root / "work/evidence.md").read_text(), "offline tool execution")
        # The image produced by the view tool really reached the next provider request.
        images = []
        for message in calls[-1]["body"]["messages"]:
            for part in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if part.get("type") == "image_url":
                    images.append(part["image_url"]["url"])
        self.assertGreaterEqual(len(images), 2)
        self.assertEqual({hashlib.sha256(base64.b64decode(url.split(",", 1)[1])).hexdigest() for url in images}, {hashlib.sha256(PNG).hexdigest()})
        self.assertNotIn("data:image", json.dumps(result))
        reopened, dispatched, _, _ = self.request("success", mode="inspect")
        self.assertTrue(reopened["ok"], reopened)
        self.assertEqual(reopened["session_id"], result["session_id"])
        self.assertEqual(dispatched, [])

    def test_real_sdk_managed_cjk_fonts_keep_complete_authored_html_editable(self):
        case = "managed_font_edit"
        work = self.root / case / "work"
        tail = "AUTHORED_DOM_TAIL_AFTER_MANAGED_FONTS"
        original_text, edited_text = "原始中文排字", "调整后的中文排字"
        authored = ("<!doctype html><html><head><meta charset=\"utf-8\"><style>\n"
                    ":root { --font-title: \"Songti SC\", serif; --field: #242421; }\n"
                    "#poster { width:1776px; height:2368px; background:var(--field); }\n"
                    ".headline { font-family:var(--font-title); font-size:118px; }\n"
                    "</style></head><body><div id=\"poster\" data-canvas-width=\"1776\" "
                    "data-canvas-height=\"2368\"><div class=\"hf-slot headline\" "
                    "data-layer-id=\"headline\">" + original_text + "</div>"
                    "<!--" + tail + "--></div></body></html>")
        faces = re.compile(r"@font-face\s*\{[^{}]*\}")
        observed = {"synthetic_fixture": True, "external_provider_calls": 0}
        saved = {}

        def font_files():
            return {p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((work / "assets/fonts/cjk-serif").rglob("*")) if p.is_file()}

        def tool_text(body, call_id):
            message = next((m for m in reversed(body["messages"])
                            if m.get("role") == "tool" and m.get("tool_call_id") == call_id), {})
            value = message.get("content", "")
            return value if isinstance(value, str) else "".join(text_values(value))

        def respond(event, calls):
            ordinal = len(calls)
            fn, arguments = None, None
            if ordinal == 1:
                check = next(t["function"] for t in event["body"]["tools"]
                             if t["function"]["name"] == "cover_check")
                # Let the old baseline reach its real SDK truncation instead of
                # stopping on a parameter its old tool schema does not expose.
                observed["css_var_supported"] = "css_var" in check["parameters"]["properties"]
                fn, arguments = "cover_write", {"path": "index.html", "text": authored}
            elif ordinal == 2:
                fn, arguments = "cover_check", {"action": "font_add", "html": "index.html",
                                                "font_id": "cjk-serif"}
                if observed["css_var_supported"]:
                    arguments["css_var"] = "--font-title"
            elif ordinal == 3:
                data = (work / "index.html").read_bytes()
                saved.update(before=data, faces=faces.findall(data.decode()), font_files=font_files())
                observed.update(installed_html_bytes=len(data), installed_faces=len(saved["faces"]),
                                font_add_tool_text=tool_text(event["body"], "managed-font-call-2"))
                fn, arguments = "cover_read", {"path": "index.html"}
            elif ordinal == 4:
                raw = tool_text(event["body"], "managed-font-call-3")
                observed.update(first_read_bytes=len(raw.encode()), tail_reached_sdk=tail in raw,
                                physical_file_unchanged_by_read=(work / "index.html").read_bytes() == saved["before"])
                try:
                    view = json.loads(raw)
                except json.JSONDecodeError:
                    view = None
                observed["first_view"] = view
                if isinstance(view, dict) and isinstance(view.get("text"), str) and tail in view["text"]:
                    saved["edited"] = view["text"].replace("#242421", "#303030", 1).replace(original_text, edited_text, 1)
                    fn, arguments = "cover_write", {"path": "index.html", "text": saved["edited"]}
            elif ordinal == 5:
                after = (work / "index.html").read_bytes()
                saved["after"] = after
                observed.update(edited_html_bytes=len(after), font_files_unchanged=font_files() == saved["font_files"],
                                managed_faces_unchanged=faces.findall(after.decode()) == saved["faces"])
                fn, arguments = "cover_read", {"path": "index.html"}
            elif ordinal == 6:
                raw = tool_text(event["body"], "managed-font-call-5")
                observed["second_view"] = json.loads(raw)
                # Identical font CSS in a different, unregistered file must not
                # inherit another HTML file's managed-font elision permission.
                fn, arguments = "cover_write", {"path": "unregistered.html",
                    "text": "<html><head><style>" + saved["faces"][0]
                    + "</style></head><body>UNREGISTERED_FONT_DOM_TAIL</body></html>"}
            elif ordinal == 7:
                fn, arguments = "cover_read", {"path": "unregistered.html"}
            elif ordinal == 8:
                observed["unregistered_read"] = tool_text(event["body"], "managed-font-call-7")
                fn, arguments = "cover_write", {"path": "notes.txt", "text": "普通文件逐字原文。\n"}
            elif ordinal == 9:
                fn, arguments = "cover_read", {"path": "notes.txt"}
            elif ordinal == 10:
                observed["ordinary_read"] = tool_text(event["body"], "managed-font-call-9")
            message = {"role": "assistant", "content": "OFFLINE_FONT_EDIT_COMPLETE" if fn is None else None}
            if fn:
                message["tool_calls"] = [{"id": "managed-font-call-" + str(ordinal), "type": "function",
                    "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            body = {"id": "chatcmpl_managed_font_fixture", "object": "chat.completion", "created": 1,
                    "model": event["body"]["model"], "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if fn else "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
            return {"type": "model_response", "id": event["id"], "status": 200, "body": body}

        result, calls, _, root = self.request(case, respond=respond)
        (root / "managed-font-observations.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
        self.assertTrue(result["ok"], result)
        self.assertGreater(observed["installed_html_bytes"], 50 * 1024)
        self.assertEqual(observed["installed_faces"], 101)
        self.assertTrue(observed["tail_reached_sdk"], "SDK truncated the actual authored DOM after the generated font CSS")
        self.assertTrue(observed["css_var_supported"])
        self.assertEqual(len(calls), 10)
        self.assertTrue(observed["physical_file_unchanged_by_read"])
        view = observed["first_view"]
        self.assertEqual(view["view"], "authored_html_with_managed_font_faces_elided")
        self.assertEqual((view["path"], view["bytes"], view["sha256"]),
                         ("index.html", len(saved["before"]), hashlib.sha256(saved["before"]).hexdigest()))
        self.assertEqual(view["omitted_font_faces"], 101)
        self.assertEqual(view["text"], faces.sub("", saved["before"].decode()))
        self.assertEqual(view["fonts"], [{"font_id": "cjk-serif", "variable": "--font-kit-cjk-serif",
                                        "family": "Noto Serif SC Variable", "face_count": 101}])
        added = json.loads(observed["font_add_tool_text"])
        self.assertEqual(added["font"], {"font_id": "cjk-serif", "variable": "--font-kit-cjk-serif",
                                          "css_var": "--font-title", "face_count": 101})
        self.assertRegex(saved["before"].decode(), r"--font-title\s*:\s*var\(--font-kit-cjk-serif\)")
        self.assertTrue(observed["font_files_unchanged"])
        self.assertTrue(observed["managed_faces_unchanged"])
        self.assertTrue(any(p.endswith("/LICENSE.txt") for p in saved["font_files"]))
        self.assertTrue(any(p.endswith(".woff2") for p in saved["font_files"]))
        self.assertEqual(faces.sub("", saved["after"].decode()), saved["edited"])
        self.assertIn(edited_text, saved["after"].decode())
        self.assertIn("#303030", saved["after"].decode())
        self.assertNotIn(original_text, saved["after"].decode())
        self.assertEqual(observed["second_view"]["text"], saved["edited"])
        self.assertEqual(observed["second_view"]["sha256"], hashlib.sha256(saved["after"]).hexdigest())
        self.assertEqual(observed["unregistered_read"], (work / "unregistered.html").read_text())
        self.assertIn(saved["faces"][0], observed["unregistered_read"])
        self.assertIn("UNREGISTERED_FONT_DOM_TAIL", observed["unregistered_read"])
        self.assertEqual(observed["ordinary_read"], "普通文件逐字原文。\n")

    def test_explicit_revision_continues_only_known_original_session_once(self):
        first, _, _, _ = self.request("revision")
        self.assertTrue(first["ok"], first)
        result, calls, _, _ = self.request("revision", mode="revise", session_id=first["session_id"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["session_id"], first["session_id"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["ordinal"], 4)
        again, calls, _, _ = self.request("revision", mode="revise", session_id=first["session_id"])
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "REVISION_REQUIRES_KNOWN_COMPLETE_SESSION")
        self.assertEqual(calls, [])
        reopened, calls, _, _ = self.request("revision", mode="inspect")
        self.assertTrue(reopened["ok"], reopened)
        self.assertEqual(calls, [])

    def test_503_vetoes_automatic_retry(self):
        result, calls, events, _ = self.request("failure", behavior="503")
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len([event for event in events if event["type"] == "retry_veto"]), 1)

    def test_active_html_cannot_reach_browser_tools(self):
        result, calls, _, root = self.request("unsafe", behavior="unsafe_html")
        self.assertTrue(result["ok"], result)
        self.assertFalse((root / "work/unsafe.html").exists())
        self.assertTrue("ACTIVE_HTML_FORBIDDEN" in json.dumps(calls[1]["body"]), "Unsafe markup was not refused")

    def test_internal_and_hidden_paths_are_not_agent_writable(self):
        for index, forbidden in enumerate(["noteai-input.json", "host-session.json", "host-state/host-checkpoint.json", ".hidden/design.json", "project/.state.json", "qc-0.json"]):
            with self.subTest(path=forbidden):
                result, calls, _, _ = self.request("internal" + str(index), forbidden_path=forbidden)
                self.assertTrue(result["ok"], result)
                self.assertTrue("INTERNAL_PATH_FORBIDDEN" in json.dumps(calls[1]["body"]), "Internal write not refused: " + forbidden)

    def test_physical_limit_applies_before_second_bridge_dispatch(self):
        result, calls, _, _ = self.request("cap", limit=1)
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)

    def test_unknown_persists_and_reopen_never_replays(self):
        result, calls, _, _ = self.request("unknown", behavior="unknown")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        reopened, dispatched, _, _ = self.request("unknown", mode="inspect")
        self.assertFalse(reopened["ok"])
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(dispatched, [])

    def test_bridge_disconnect_retains_original_pending_request(self):
        result, calls, _, _ = self.request("disconnect", behavior="disconnect")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        reopened, calls, _, _ = self.request("disconnect", mode="inspect")
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(calls, [])

    def context_responder(self, *, malformed_summary=False, view_before_compaction=False):
        state = {"primary": 0, "compactions": 0, "viewed_after_compaction": False}
        paragraph = "离线设计说明，保留真实照片与批准标题，不增添商家事实。\n"

        def respond(event, calls):
            label = event.get("label")
            fn, arguments = None, None
            if label == "compaction":
                state["compactions"] += 1
                content = "NOT_A_STRUCTURED_SUMMARY" if malformed_summary else (
                    "## Objective\n- Continue the offline cover fixture.\n"
                    "## Requirements\n- Preserve approved facts, title and original files.\n"
                    "## Decisions\n- No generated photos are deliverable.\n"
                    "## Work State\n### Completed\n- Wrote local design notes.\n"
                    "### Active\n- Inspect the original photo and finish.\n"
                    "### Blocked\n- (none)\n## Next Move\n1. View source-1.png.\n"
                    "## Relevant Files\n- source-1.png: original pixels.\n"
                    "## Important Context\n- This is a synthetic, provider-free fixture.")
            elif state["compactions"]:
                if not state["viewed_after_compaction"]:
                    state["viewed_after_compaction"] = True
                    fn, arguments = "cover_view", {"path": "source-1.png"}
                    content = None
                else:
                    content = "OFFLINE_COMPLETE"
            else:
                state["primary"] += 1
                self.assertLessEqual(state["primary"], 16, "Long SDK transcript never exercised the real input bound")
                if view_before_compaction and state["primary"] == 1:
                    fn, arguments = "cover_view", {"path": "source-2.png"}
                else:
                    fn, arguments = "cover_write", {"path": "design-step-" + str(state["primary"]) + ".md",
                                                     "text": paragraph * 160}
                content = None
            message = {"role": "assistant", "content": content}
            if fn:
                message["tool_calls"] = [{"id": "context_call_" + str(len(calls)), "type": "function",
                                          "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            body = {"id": "chatcmpl_context_fixture", "object": "chat.completion", "created": 1,
                    "model": event["body"]["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if fn else "stop"}],
                    "usage": {"prompt_tokens": max(1, sum(len(t) for t in text_values(event["body"])) // 4
                                                      + 1500 * len(image_hashes(event["body"]))),
                              "completion_tokens": 2000 if fn == "cover_write" else 100}}
            body["usage"]["total_tokens"] = body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
            return {"type": "model_response", "id": event["id"], "status": 200, "body": body}

        return respond

    def stored_write_receipts(self, root, session_id):
        # Read only this test's own synthetic session through the public SDK.
        # No direct SQLite access, provider transport, or live application state.
        script = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const [modules, root, sessionID] = process.argv.slice(1);
globalThis.fetch = async () => { throw new Error('OFFLINE_HISTORY_FORBIDS_NETWORK'); };
const load = (name) => import(pathToFileURL(path.join(modules, name)).href);
const { create } = await load('@opencode/sdk/dist/promise.js');
const { Global } = await load('@opencode/util/dist/global.js');
const { Config } = await load('@opencode/core/dist/config.js');
const home = path.join(root, 'state', 'isolated');
const cfg = { project: false, global: false, system: false, claude: false,
  content: JSON.stringify({ providers: {}, skills: [], update: 'disable' }) };
const sdk = await create({ config: cfg, database: { path: path.join(root, 'state/session.sqlite') },
  models: { fetch: false, snapshot: false }, fs: { filewatcher: false, fff: false }, log: { level: 'error' } },
  { overrides: [Global.node.replace(Global.layerWith({ home, data: path.join(home, 'data'),
    config: path.join(home, 'config'), cache: path.join(home, 'cache'), state: path.join(home, 'state'),
    tmp: path.join(home, 'tmp'), bin: path.join(home, 'bin'), log: path.join(home, 'log'),
    repos: path.join(home, 'repos') })), Config.node.replace(Config.configured(cfg))] });
try {
  const { messages: context } = await sdk.sessions.export({ sessionID, sanitize: false });
  const writes = context.flatMap((message) => message.type === 'assistant' ? (message.content || []) : [])
    .filter((part) => part.type === 'tool' && part.name === 'cover_write' && typeof part.state?.input?.text === 'string')
    .map((part) => ({ id: part.id, path: part.state.input.path, bytes: Buffer.byteLength(part.state.input.text),
      sha256: createHash('sha256').update(part.state.input.text).digest('hex') }));
  console.log(JSON.stringify({ writes, opaque_present: JSON.stringify(context).includes('TEST_OPAQUE_COVER_') }));
} finally { await sdk.close(); }
"""
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "HOME": str(root / "state/isolated"),
               "OPENCODE_TEST_HOME": str(root / "state/isolated"), "OPENCODE_DISABLE_FREE_MODELS": "true"}
        checked = subprocess.run([self.node, "--input-type=module", "-e", script,
                                  self.modules, str(root), session_id], env=env,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr[-2000:])
        exported = json.loads(checked.stdout)
        self.assertFalse(exported["opaque_present"], "Opaque thinking leaked into public SDK export")
        receipts = exported["writes"]
        (root / "stored-original-write-receipts.json").write_text(json.dumps(receipts, indent=2))
        return receipts

    def opaque_responder(self, responder, *, prefix, empty_at=()):
        originals, ciphers = [], []

        def respond(event, calls):
            for message in event["body"]["messages"]:
                if message["role"] == "assistant":
                    self.assertIn(message, originals, "Supplier replay changed the original signed assistant message")
            answer = responder(event, calls)
            if answer.get("status") == 200:
                message = answer["body"]["choices"][0]["message"]
                message["reasoning_content"] = "合成思考摘要，不是加密原文"
                message["encrypted_content"] = ("" if len(calls) in empty_at else
                    "TEST_OPAQUE_COVER_" + prefix + "_" + str(len(calls)))
                originals.append(deepcopy(message)); ciphers.append(message["encrypted_content"])
            return answer

        return respond, originals, ciphers

    def assert_no_sdk_cipher(self, result, events, root, ciphers, *, mode="run"):
        visible = json.dumps(events) + (root / (mode + "-success-responses.json")).read_text()
        visible += (root / (mode + "-success-stderr.txt")).read_text()
        visible += (root / "state/host-checkpoint.json").read_text()
        self.assertTrue(ciphers)
        for cipher in ciphers:
            if cipher:
                self.assertNotIn(cipher, visible)
        self.stored_write_receipts(root, result["session_id"])

    def test_real_sdk_empty_encrypted_turn_keeps_exact_history_and_compacts(self):
        respond, originals, ciphers = self.opaque_responder(
            self.context_responder(view_before_compaction=True), prefix="empty", empty_at=(2,))
        result, calls, events, root = self.request("empty_context", admission=provider_admission(),
            respond=respond, nine_photos=True, thinking=ThinkingState("empty_context"))
        self.assertTrue(result["ok"], result)
        supplier = json.loads((root / "run-success-synthetic-supplier-bodies.json").read_text())
        replayed = [message for body in supplier for message in body["messages"]
                    if message["role"] == "assistant" and "encrypted_content" in message]
        self.assertTrue(any(message["encrypted_content"] == "" for message in replayed))
        self.assertTrue(any(message["encrypted_content"] for message in replayed))
        self.assertTrue(all(message in originals for message in replayed))
        self.assertEqual(sum(call.get("label") == "compaction" for call in calls), 1)
        responses = json.loads((root / "run-success-responses.json").read_text())
        self.assertTrue(all("encrypted_content" not in response["body"]["choices"][0]["message"]
                            for response in responses))
        self.assert_no_sdk_cipher(result, events, root, ciphers)

    def test_real_sdk_opaque_replay_and_fresh_summary_keep_original_state(self):
        admission = provider_admission()
        thinking = ThinkingState("opaque_context")
        respond, originals, ciphers = self.opaque_responder(
            self.context_responder(view_before_compaction=True), prefix="context")
        result, calls, events, root = self.request("opaque_context", admission=admission,
            respond=respond, nine_photos=True, thinking=thinking)
        self.assertTrue(result["ok"], result)
        supplier = json.loads((root / "run-success-synthetic-supplier-bodies.json").read_text())
        self.assertTrue(any(message.get("encrypted_content") for body in supplier
                            for message in body["messages"] if message["role"] == "assistant"))
        summaries = [body for body, call in zip(supplier, calls) if call.get("label") == "compaction"]
        self.assertEqual(len(summaries), 1)
        self.assertTrue(all(message["role"] in {"system", "user"} for message in summaries[0]["messages"]))
        self.assertEqual(summaries[0].get("max_tokens", summaries[0].get("max_completion_tokens")), 8192)
        summary_text = "\n".join(text_values(summaries[0]))
        self.assertIn("Previously viewed image; retrieve the original file with cover_view", summary_text)
        self.assertIn(hashlib.sha256((root / "work/source-2.png").read_bytes()).hexdigest(), summary_text)
        self.assertNotIn("data:image/", summary_text, "Summary serialized tool image bytes into text")
        self.assert_no_sdk_cipher(result, events, root, ciphers)

    def test_real_sdk_same_python_memory_replays_across_two_hosts(self):
        thinking = ThinkingState("opaque_revision")
        originals, ciphers = [], []

        def reply(phase):
            def respond(event, calls):
                for message in event["body"]["messages"]:
                    if message["role"] == "assistant":
                        self.assertIn(message, originals)
                ordinal = len(calls)
                message = {"role": "assistant", "content": "COMPLETE_" + phase}
                if ordinal == 1:
                    message["content"] = ""
                    message["tool_calls"] = [{"id": "call_" + phase, "type": "function", "function": {
                        "name": "cover_write", "arguments": '{ "text" : "真实中文与参数 1", "path" : "' + phase + '.md" }'}}]
                message["encrypted_content"] = "TEST_OPAQUE_COVER_" + phase + "_" + str(ordinal)
                originals.append(deepcopy(message)); ciphers.append(message["encrypted_content"])
                return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                    "id": "fixture", "object": "chat.completion", "created": 1, "model": event["body"]["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if ordinal == 1 else "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}}
            return respond

        first, calls, events, root = self.request("opaque_revision", respond=reply("first"), thinking=thinking)
        self.assertTrue(first["ok"], first)
        self.assertEqual(len(calls), 2)
        self.assert_no_sdk_cipher(first, events, root, ciphers)
        count_before = thinking.entry_count
        revised, next_calls, next_events, _ = self.request("opaque_revision", mode="revise",
            session_id=first["session_id"], respond=reply("revised"), thinking=thinking)
        self.assertTrue(revised["ok"], revised)
        self.assertEqual(len(next_calls), 2)
        self.assertGreater(thinking.entry_count, count_before)
        self.assertEqual(revised["session_id"], first["session_id"])
        self.assert_no_sdk_cipher(revised, next_events, root, ciphers, mode="revise")

    def test_real_sdk_opaque_memory_does_not_replay_unknown_response(self):
        thinking = ThinkingState("opaque_unknown")

        def respond(event, calls):
            if len(calls) > 1:
                return {"type": "model_response", "id": event["id"], "unknown": True}
            return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                "id": "fixture", "object": "chat.completion", "created": 1, "model": event["body"]["model"],
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                    "encrypted_content": "TEST_OPAQUE_COVER_unknown_1", "tool_calls": [{"id": "unknown_first", "type": "function",
                        "function": {"name": "cover_write", "arguments": '{"path":"known.md","text":"known before unknown"}'}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}}

        result, calls, events, _ = self.request("opaque_unknown", respond=respond, thinking=thinking)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 2)
        self.assertEqual(thinking.entry_count, 1)
        self.assertFalse(any(call.get("label") == "compaction" for call in calls))
        inspected, new_calls, _, _ = self.request("opaque_unknown", mode="inspect", thinking=thinking)
        self.assertEqual(inspected["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(new_calls, [])

    def test_real_sdk_nine_photos_compacts_before_local_input_bound_without_supplier(self):
        admission = provider_admission()
        result, calls, events, root = self.request("context_bound", admission=admission,
            respond=self.context_responder(), nine_photos=True)
        self.assertTrue(result["ok"], {"status": result.get("status"), "errors": [
            entry["error"] for entry in result.get("context", []) if entry.get("error")]})
        rejections = [event for event in events if event["type"] == "model_preflight"]
        measured = [admission["admit_payload"](event["body"]) for event in rejections]
        rejected = [value for value in measured if value["allowed"] is False]
        self.assertTrue(rejected, "Actual SDK never reached the unchanged real provider bound")
        self.assertTrue(all(value["code"] == "COVER_AGENT_INPUT_LIMIT_EXCEEDED"
                            and value["measurement"]["total_bound"] > admission["MAX_INPUT_TOKENS"]
                            for value in rejected))
        compactions = [call for call in calls if call.get("label") == "compaction"]
        self.assertEqual(len(compactions), 1)
        self.assertEqual(compactions[0]["body"].get("max_tokens", compactions[0]["body"].get("max_completion_tokens")), 8192)
        self.assertTrue(all(message["role"] in {"system", "user"}
                            and not message.get("tool_calls") for message in compactions[0]["body"]["messages"]),
                        "Standalone summary reused active assistant/tool records")
        self.assertTrue(all(call["body"].get("max_tokens", call["body"].get("max_completion_tokens")) == 65536
                            for call in calls if call.get("label") == "primary"))
        compact_index = calls.index(compactions[0])
        continued = calls[compact_index + 1:]
        self.assertEqual(len(continued), 2, "Expected fresh original view then normal completion")
        skill = (PROJECT / "model/cover_editable/vendor/editable-design/SKILL.md").read_text()
        for call in continued:
            text = "\n".join(text_values(call["body"]))
            self.assertIn(skill, text, "Full fixed Skill did not survive SDK compaction")
            self.assertIn("批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。", text)
            for index in range(1, 10):
                photo = root / ("work/source-" + str(index) + ".png")
                self.assertIn(photo.name, text)
                self.assertIn(hashlib.sha256(photo.read_bytes()).hexdigest(), text)
        original_hashes = {hashlib.sha256((root / ("work/source-" + str(index) + ".png")).read_bytes()).hexdigest()
                           for index in range(1, 10)}
        self.assertEqual(set(image_hashes(calls[0]["body"])), original_hashes)
        self.assertLess(len(image_hashes(continued[0]["body"])), 9, "Compaction reinserted all original image bytes")
        self.assertIn(hashlib.sha256((root / "work/source-1.png").read_bytes()).hexdigest(), image_hashes(continued[-1]["body"]))
        for call in calls:
            _, bound = admission["prepare_payload"](call["body"])
            self.assertLessEqual(bound, admission["MAX_INPUT_TOKENS"])
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["model_requests"], len(calls))
        self.assertEqual(checkpoint["local_input_rejections"], len(rejected))
        self.assertEqual(checkpoint["compaction_requests"], 1)
        self.assertIsNone(checkpoint.get("pending_request"))
        responses = json.loads((root / "run-success-responses.json").read_text())
        original_writes = [tool for response in responses for choice in response.get("body", {}).get("choices", [])
                           for tool in choice["message"].get("tool_calls", [])
                           if tool["function"]["name"] == "cover_write"]
        expected = {}
        for tool in original_writes:
            arguments = json.loads(tool["function"]["arguments"])
            expected.setdefault(tool["id"], {"id": tool["id"], "path": arguments["path"],
                                             "bytes": len(arguments["text"].encode()),
                                             "sha256": hashlib.sha256(arguments["text"].encode()).hexdigest()})
        stored = {row["id"]: row for row in self.stored_write_receipts(root, result["session_id"])}
        self.assertTrue(expected)
        self.assertEqual(stored, expected, "Compaction mutated original session write text")
        for event in events:
            if event["type"] != "model_preflight" or event.get("label") != "primary":
                continue
            for message in event["body"]["messages"]:
                for tool in message.get("tool_calls", []):
                    if tool["id"] not in expected:
                        continue
                    arguments = json.loads(tool["function"]["arguments"])
                    self.assertEqual(hashlib.sha256(arguments["text"].encode()).hexdigest(),
                                     expected[tool["id"]]["sha256"], "UTF-8 primary replay changed original text")

    def test_real_sdk_unknown_nine_photo_result_never_compacts_or_replays(self):
        admission = provider_admission()
        result, calls, events, _ = self.request("context_unknown", admission=admission, nine_photos=True,
            respond=lambda event, _: {"type": "model_response", "id": event["id"], "unknown": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("label"), "primary")
        self.assertFalse(any(event["type"] == "model_preflight" and event.get("label") == "compaction" for event in events))
        reopened, calls, _, _ = self.request("context_unknown", mode="inspect")
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(calls, [])

    def test_real_sdk_malformed_summary_cannot_dispatch_a_second_paid_attempt(self):
        admission = provider_admission()
        result, calls, _, root = self.request("context_malformed", admission=admission,
            respond=self.context_responder(malformed_summary=True), nine_photos=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "FAILED")
        compactions = [call for call in calls if call.get("label") == "compaction"]
        self.assertEqual(len(compactions), 1, "SDK NUDGE generated another admitted model call")
        self.assertEqual(calls[-1], compactions[0])
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["compaction_requests"], 1)
        self.assertIsNone(checkpoint.get("pending_request"))


if __name__ == "__main__":
    unittest.main()
