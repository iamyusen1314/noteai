"""Build-only attachment concurrency patch; no images, DB or provider calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "model/cover_agent_host/apply-sdk-attachment-memory-compat.mjs"
CHUNK = "dist/chunks/repository-cache-3xcrjpsd.js"
OLD = "9c74c7aa0923e21ec0df7ee48c2574f75252acc7488c9af2dc8333e1615d64cb"
NEW = "bfbd1ac398c1cc6be27c22535daae0b05eb90005ab825b052a003110be74f8f3"


class AttachmentMemoryPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modules = os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES")
        core = os.environ.get("NOTEAI_COVER_CORE_SOURCE")
        cls.node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        cls.source = Path(core) / CHUNK if core else Path(modules) / "@opencode/core" / CHUNK if modules else None
        if not cls.node or cls.source is None or not cls.source.is_file():
            raise unittest.SkipTest("Existing pinned OpenCode core and node required")
        cls.original = cls.source.read_bytes()
        if hashlib.sha256(cls.original).hexdigest() != OLD:
            raise unittest.SkipTest("Unmodified pinned attachment chunk required")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="noteai-attachment-patch-")
        self.modules = Path(self.temp.name) / "node_modules"
        for name in ("sdk", "core"):
            package = self.modules / "@opencode" / name
            package.mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"name": "@opencode/" + name, "version": "2.1.2"}))
        self.chunk = self.modules / "@opencode/core" / CHUNK
        self.chunk.parent.mkdir(parents=True)
        self.chunk.write_bytes(self.original)
        self.chunk.chmod(0o640)

    def tearDown(self):
        self.temp.cleanup()

    def patch(self):
        return subprocess.run([self.node, str(PATCHER), str(self.modules)], capture_output=True,
            text=True, timeout=15, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})

    def test_only_one_literal_changes_and_second_apply_preserves_file(self):
        result = self.patch()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["before_sha256"], receipt["after_sha256"]), (OLD, NEW))
        patched = self.chunk.read_bytes()
        self.assertEqual(len(patched), 8209)
        differences = [i for i, (old, new) in enumerate(zip(self.original, patched)) if old != new]
        self.assertEqual(len(differences), 1)
        self.assertEqual((self.original[differences[0]], patched[differences[0]]), (ord("8"), ord("1")))
        self.assertEqual(self.chunk.stat().st_mode & 0o777, 0o640)
        modified = self.chunk.stat().st_mtime_ns
        again = self.patch()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["status"], "already_patched")
        self.assertEqual(self.chunk.stat().st_mtime_ns, modified)
        self.assertEqual(self.chunk.read_bytes(), patched)
        self.assertFalse(list(self.chunk.parent.glob("*.noteai-*.tmp")))

    def test_unknown_original_or_modified_patch_is_rejected_without_write(self):
        for original in (True, False):
            with self.subTest(original=original):
                self.chunk.write_bytes(self.original)
                if not original:
                    self.assertEqual(self.patch().returncode, 0)
                changed = self.chunk.read_bytes() + b"\n// unknown change\n"
                self.chunk.write_bytes(changed)
                result = self.patch()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stderr)["code"], "SDK_ATTACHMENT_SOURCE_MISMATCH")
                self.assertEqual(self.chunk.read_bytes(), changed)
                self.assertEqual(result.stdout, "")

    def test_wrong_sdk_or_core_version_is_rejected(self):
        for name in ("sdk", "core"):
            with self.subTest(name=name):
                package = self.modules / "@opencode" / name / "package.json"
                before = package.read_bytes()
                package.write_text('{"version":"2.1.3"}')
                result = self.patch()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stderr)["code"], "SDK_ATTACHMENT_VERSION_MISMATCH")
                self.assertEqual(self.chunk.read_bytes(), self.original)
                package.write_bytes(before)

    def test_symlink_target_is_rejected(self):
        original = self.chunk.with_suffix(".retained")
        self.chunk.rename(original)
        self.chunk.symlink_to(original)
        result = self.patch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "SDK_ATTACHMENT_REGULAR_FILE_REQUIRED")
        self.assertEqual(original.read_bytes(), self.original)
