"""Offline integration proof against the installed, real OpenCode 2.1.2 SDK.

NOTEAI_COVER_HOST_NODE_MODULES points to the task-local exact installation.
No remote model endpoint, credential, account, or product database is involved.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNQKJhAEmIY1TCqYfhqAACs2CAQru0W7wAAAABJRU5ErkJggg==")


class HostProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES")
        cls.node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not cls.modules or not cls.node:
            raise unittest.SkipTest("Explicit task-local OpenCode installation and node required")
        cls.root = Path(tempfile.mkdtemp(prefix="noteai-cover-host-proof-"))
        cls.receipts = []

    @classmethod
    def tearDownClass(cls):
        receipt = {"real_model_requests": 0, "sdk_version": "2.1.2", "fixtures": cls.receipts}
        (cls.root / "proof-results.json").write_text(json.dumps(receipt, indent=2))
        output = os.environ.get("NOTEAI_COVER_HOST_PROOF_OUTPUT")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            shutil.copytree(cls.root, Path(output) / cls.root.name)
        print("HOST_PROOF_EVIDENCE=" + str(cls.root))

    def request(self, case, *, mode="run", limit=None, behavior="success", session_id=None, forbidden_path=None):
        root = self.root / case
        (root / "work").mkdir(parents=True, exist_ok=True)
        (root / "work/photo.png").write_bytes(PNG)
        start = {
            "type": "start", "job_id": case, "state_dir": str(root / "state"),
            "work_dir": str(root / "work"),
            "skill_dir": str(PROJECT / "model/cover_editable/vendor/editable-design"),
            "editable_cli": str(PROJECT / "model/cover_editable/cli.mjs"),
            "model_id": "offline-fixture", "prompt": "Offline proof only. Follow the returned tool calls and finish. Do not generate artwork.",
            "images": [{"path": "photo.png"}], "max_model_requests": limit,
            "deadline_epoch_ms": int((time.time() + 60) * 1000), "mode": mode,
        }
        if session_id:
            start["session_id"] = session_id
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "NOTEAI_COVER_HOST_NODE_MODULES": self.modules}
        for key in ["EDITABLE_DESIGN_BROWSER", "PUPPETEER_EXECUTABLE_PATH", "NO_SANDBOX", "EDITABLE_DESIGN_NO_SANDBOX"]:
            if os.environ.get(key):
                env[key] = os.environ[key]
        proc = subprocess.Popen([self.node, str(HERE / "worker.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, bufsize=1)
        proc.stdin.write(json.dumps(start) + "\n"); proc.stdin.flush()
        events, calls = [], []
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
                if event["type"] == "model_request":
                    calls.append(event)
                    if behavior == "disconnect":
                        proc.stdin.close()
                        continue
                    if behavior == "unknown":
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
        (root / (mode + "-" + behavior + "-stderr.txt")).write_text(stderr)
        result = next((event for event in reversed(events) if event["type"] == "result"), None)
        self.assertIsNotNone(result, stderr)
        self.receipts.append({"case": case, "mode": mode, "behavior": behavior, "model_bridge_requests": len(calls), "result": result, "events_file": str(root / (mode + "-" + behavior + "-events.json"))})
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


if __name__ == "__main__":
    unittest.main()
