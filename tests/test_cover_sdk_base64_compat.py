"""Pinned-SDK large-photo regression; no DB, dotenv, network or model calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
PATCHER = PROJECT / "model/cover_agent_host/apply-sdk-base64-compat.mjs"
ORIGINAL_SHA = "2fd973e0fac2f8fe9025ced5a3ba410768ab99806143e70e4388044f27f325b4"
PATCHED_SHA = "90e473112cca6e5cda43aceb63bddc1daa1adb028f96f1e7796896b52c410904"


class CoverSdkBase64CompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modules = os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES")
        cls.node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not modules or not cls.node:
            raise unittest.SkipTest("Explicit existing OpenCode 2.1.2 modules and node required")
        cls.original_modules = Path(modules)
        cls.original_prompt = cls.original_modules / "@opencode/schema/dist/prompt.js"
        if hashlib.sha256(cls.original_prompt.read_bytes()).hexdigest() != ORIGINAL_SHA:
            raise unittest.SkipTest("Unmodified pinned schema required for the old-failure control")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="noteai-sdk-base64-test-")
        self.root = Path(self.temp.name)
        self.modules = self.root / "node_modules"
        schema = self.modules / "@opencode/schema"
        schema.parent.mkdir(parents=True)
        shutil.copytree(self.original_modules / "@opencode/schema", schema)
        sdk = self.modules / "@opencode/sdk"
        sdk.mkdir()
        (sdk / "package.json").write_text(json.dumps({"name": "@opencode/sdk", "version": "2.1.2"}))
        (self.modules / "effect").symlink_to(self.original_modules / "effect", target_is_directory=True)
        self.prompt = schema / "dist/prompt.js"
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def tearDown(self):
        self.temp.cleanup()

    def patch(self):
        return subprocess.run([self.node, str(PATCHER), str(self.modules)], capture_output=True,
                              text=True, env=self.env, timeout=15)

    def test_exact_patch_and_second_application_preserve_bytes(self):
        first = self.patch()
        self.assertEqual(first.returncode, 0, first.stderr)
        receipt = json.loads(first.stdout)
        self.assertEqual((receipt["status"], receipt["before_sha256"], receipt["after_sha256"]),
                         ("patched", ORIGINAL_SHA, PATCHED_SHA))
        body, modified = self.prompt.read_bytes(), self.prompt.stat().st_mtime_ns
        self.assertEqual(hashlib.sha256(body).hexdigest(), PATCHED_SHA)
        second = self.patch()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "already_patched")
        self.assertEqual(self.prompt.read_bytes(), body)
        self.assertEqual(self.prompt.stat().st_mtime_ns, modified)
        self.assertFalse(list(self.prompt.parent.glob("*.noteai-*.tmp")))
        self.assertNotIn(str(self.root), first.stdout + first.stderr + second.stdout + second.stderr)

    def test_unknown_source_is_rejected_without_mutation(self):
        changed = self.prompt.read_bytes() + b"\n// unknown downstream change\n"
        self.prompt.write_bytes(changed)
        result = self.patch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr), {"code": "SDK_BASE64_SOURCE_MISMATCH"})
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.prompt.read_bytes(), changed)
        self.assertFalse(list(self.prompt.parent.glob("*.noteai-*.tmp")))

    def test_modified_patched_file_is_not_accepted_as_idempotent(self):
        self.assertEqual(self.patch().returncode, 0)
        changed = self.prompt.read_bytes().replace(b"length % 4", b"length % 2", 1)
        self.prompt.write_bytes(changed)
        result = self.patch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "SDK_BASE64_SOURCE_MISMATCH")
        self.assertEqual(self.prompt.read_bytes(), changed)

    def test_different_sdk_or_schema_version_is_rejected(self):
        original = self.prompt.read_bytes()
        for package in ("sdk", "schema"):
            with self.subTest(package=package):
                metadata = self.modules / "@opencode" / package / "package.json"
                before = metadata.read_bytes()
                value = json.loads(before)
                value["version"] = "2.1.3"
                metadata.write_text(json.dumps(value))
                result = self.patch()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stderr)["code"], "SDK_BASE64_VERSION_MISMATCH")
                self.assertEqual(self.prompt.read_bytes(), original)
                metadata.write_bytes(before)

    def test_symbolic_target_is_rejected_without_touching_destination(self):
        destination = self.root / "retained-original.js"
        self.prompt.rename(destination)
        self.prompt.symlink_to(destination)
        result = self.patch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "SDK_BASE64_REGULAR_FILE_REQUIRED")
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), ORIGINAL_SHA)

    def test_real_schema_large_photo_and_contract_equivalence(self):
        self.assertEqual(self.patch().returncode, 0)
        script = r'''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const [patchedFile, originalFile, effectFile] = process.argv.slice(2);
const patched = await import(pathToFileURL(patchedFile));
const original = await import(pathToFileURL(originalFile));
const { Schema } = await import(pathToFileURL(effectFile));
const oldFilter = original.Base64.ast.checks[0].annotations;
const newFilter = patched.Base64.ast.checks[0].annotations;
assert.deepEqual(patched.Base64.ast.annotations, original.Base64.ast.annotations);
assert.deepEqual(newFilter.representation, oldFilter.representation);
assert.deepEqual(newFilter.arbitraryConstraint, oldFilter.arbitraryConstraint);
assert.equal(newFilter.expected, oldFilter.expected);
assert.deepEqual(newFilter.toCode(), oldFilter.toCode());
assert.deepEqual(Schema.toJsonSchemaDocument(patched.Base64), Schema.toJsonSchemaDocument(original.Base64));
const oldAccepts = Schema.is(original.Base64), accepts = Schema.is(patched.Base64);
let checked = 0;
const compare = (value) => { assert.equal(accepts(value), oldAccepts(value)); checked++; };
// The larger 299606-case differential was already recorded during triage.
function walk(value, depth) {
  compare(value);
  if (depth) for (const char of ['A', 'a', '0', '+', '/', '=', '_', '\n']) walk(value + char, depth - 1);
}
walk('', 4);
for (const value of ['', 'AA==', 'AB==', 'AAA=', 'AAB=', 'AAAA', 'A===', '====',
  'AA=A', 'AAAA\n', 'AAAA\r\n', 'AAAA\u2028', 'AAAA\u2029', 'éAAA', 'ＡAAA', '😀AA']) compare(value);
for (const value of [null, true, 12, {}, []]) assert.equal(accepts(value), false);
const large = Buffer.alloc(10 * 1024 * 1024, 17).toString('base64');
let oldFailure;
try { original.Base64.make(large); } catch (error) { oldFailure = error.name; }
assert.equal(oldFailure, 'RangeError', 'Old pinned filter must reproduce the large-photo stack overflow');
for (const length of [10 * 1024 * 1024, 10 * 1024 * 1024 - 1, 10 * 1024 * 1024 - 2]) {
  const value = Buffer.alloc(length, 17).toString('base64');
  assert.equal(patched.Base64.make(value), value);
}
const attachment = patched.FileAttachment.create({ data: large, mime: 'image/jpeg', source: { type: 'inline' } });
assert.equal(attachment.data, large, 'Attachment construction must retain exact input bytes');
const invalid = ['!' + large.slice(1), large.slice(0, -1) + '!',
  large.slice(0, 100) + '=' + large.slice(101), large + 'A',
  large.slice(0, -3) + '===', large + '\n'];
for (const value of invalid) assert.equal(accepts(value), false);
console.log(JSON.stringify({ runtime: process.version, short_differential_cases: checked,
  old_large_failure: oldFailure, large_base64_chars: large.length,
  new_large_legal: 3, new_large_invalid: invalid.length,
  metadata_equal: true, file_attachment_exact: true, provider_calls: 0 }));
'''
        result = subprocess.run([self.node, "--input-type=module", "-", str(self.prompt),
                                 str(self.original_prompt), str(self.original_modules / "effect/dist/index.js")],
                                input=script, capture_output=True, text=True, env=self.env, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr[:2000])
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["old_large_failure"], "RangeError")
        self.assertEqual(receipt["large_base64_chars"], 13981016)
        self.assertTrue(receipt["metadata_equal"] and receipt["file_attachment_exact"])
        self.assertEqual(receipt["provider_calls"], 0)
        print("SDK_BASE64_PROOF=" + json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
