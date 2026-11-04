"""Actual local render-tool/CLI contracts; synthetic photo, no supplier calls.

The production registration and callback are evaluated verbatim, as in the
existing runtime diagnostic fixture. The business approval reply is synthetic;
the CLI, its checks, browser screenshot and host thumbnail are real. SDK schema
registration/validation is covered separately by the runtime SDK fixture.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from PIL import Image

from tests import test_cover_agent_artifacts as artifact_tests


class RenderToolCLIContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = artifact_tests.AgentTitleCLIContractTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def actual_host(self, *, change=None, root_project=False):
        fixture = self.fixture
        if root_project:
            for item in fixture.project.iterdir():
                item.rename(fixture.directory / item.name)
            fixture.project.rmdir()
        # Only fields the model is permitted to author. Host-owned policy and
        # output paths must still be added by the actual callback.
        request = {key: deepcopy(fixture.request[key]) for key in
                   ("sources", "text_layers", "protected_regions")}
        if not root_project:
            request["project_dir"] = "project"
        if change:
            change(request)
        input_path = fixture.directory / "tool-input.json"
        input_path.write_text(json.dumps({"request": request,
            "approved_titles": fixture.request["approved_titles"]}), encoding="utf-8")
        state = fixture.directory / "host-state"
        state.mkdir()
        source = fixture.model / "cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const [sourcePath, inputPath, directory, cli, skillDir] = process.argv.slice(1);
const source = await fs.readFile(sourcePath, 'utf8');
const input = JSON.parse(await fs.readFile(inputPath, 'utf8'));
const {makeThumbnail} = await import(pathToFileURL(path.join(path.dirname(sourcePath), 'thumbnail.mjs')).href);
let callback, schema, bridgeCalls = 0, runCalls = 0, rawResult, cliRequest;
const sent = [], checkpointPath = path.join(directory, 'host-state/checkpoint.json');
const ctx = vm.createContext({fs, path, spawn, process, Buffer, setTimeout, clearTimeout,
  localChildren: new Set(), requests: 0, lastRender: null, lastPreview: null,
  checkpoint: {status: 'RUNNING', model_requests: 0, pending_request: null}, checkpointPath,
  job: {work_dir: directory, editable_cli: cli, skill_dir: skillDir},
  error: code => Object.assign(new Error(code), {code}), makeThumbnail,
  tool: (name, description, inputSchema, execute) => {
    assert.equal(name, 'cover_render'); schema = inputSchema; callback = execute;
  },
  bridge: async (type, value) => {
    assert.equal(type, 'tool_request'); assert.equal(value.name, 'cover_render');
    bridgeCalls++; return {result: {allowed: true, approved_titles: input.approved_titles,
      canonical_sources: input.request.sources}};
  },
  send: event => sent.push(event),
});
const oneLine = name => {
  const match = source.match(new RegExp('^function ' + name + '\\([^\\n]+$', 'm'));
  assert(match, name + ' actual source anchor'); return match[0];
};
vm.runInContext(oneLine('inside') + '\n' + oneLine('objectSchema') + '\n'
  + source.slice(source.indexOf('async function atomicJSON('), source.indexOf('function imageMime('))
  + source.slice(source.indexOf('async function runLocal('), source.indexOf('function completionSSE('))
  + source.slice(source.indexOf('const RENDER_REJECTION_CODES ='), source.indexOf('function summaryMaterial(')), ctx);
const runLocal = ctx.runLocal;
ctx.runLocal = async (...args) => {
  runCalls++; cliRequest = JSON.parse(args[3]);
  assert.equal(cliRequest.schema_version, 'noteai-cover-editable/v1');
  assert.equal(cliRequest.output_root, path.join(directory, 'revisions'));
  assert.equal(cliRequest.project_dir, path.resolve(directory, input.request.project_dir || '.'));
  assert.deepEqual(JSON.parse(JSON.stringify(cliRequest.approved_titles)), input.approved_titles);
  const run = await runLocal(...args); rawResult = JSON.parse(run.stdout); return run;
};
const registration = source.slice(source.indexOf("    tool('cover_render',"),
  source.indexOf("    tool('cover_check',")).trim().replace(/,$/, '');
assert(registration.startsWith("tool('cover_render',"));
vm.runInContext(registration, ctx);
assert.equal(typeof callback, 'function');
const returned = JSON.parse((await callback({request: input.request})).content);
assert.equal(bridgeCalls, 1); assert.equal(runCalls, 1);
assert.equal(rawResult.model_calls, 0);
assert.equal(ctx.localChildren.size, 0);
if (rawResult.ok) {
  assert.equal(sent.length, 1); assert.equal(sent[0].type, 'render_finished');
  assert.equal(ctx.checkpoint.artifact.png_sha256, rawResult.png_sha256);
  assert.equal(ctx.checkpoint.preview.source_sha256, rawResult.png_sha256);
  assert.equal(rawResult.external_requests, 0);
} else {
  assert.deepEqual(returned, rawResult); // Agent receives the unchanged CLI error.
  assert.equal(sent.length, 0); assert(!ctx.checkpoint.artifact);
}
console.log(JSON.stringify({schema, returned, raw: rawResult,
  checkpoint: JSON.parse(await fs.readFile(checkpointPath, 'utf8')),
  bridge_calls: bridgeCalls, cli_calls: runCalls, supplier_calls: 0,
  synthetic_business_approval: true, actual_cli: true}));
'''
        result = subprocess.run([fixture.node, "--input-type=module", "-e", script,
            str(source), str(input_path), str(fixture.directory.resolve()), str(fixture.cli),
            str(fixture.model / "cover_editable/vendor/editable-design")],
            capture_output=True, text=True, timeout=180, env=fixture.env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-4096:])
        value = json.loads(result.stdout)
        self.assertEqual((value["bridge_calls"], value["cli_calls"], value["supplier_calls"]), (1, 1, 0))
        self.assertTrue(value["actual_cli"])
        self.assertTrue(value["synthetic_business_approval"])
        return value

    def test_actual_registration_and_callback_render_model_owned_request(self):
        value = self.actual_host()
        schema = value["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["request"])
        request = schema["properties"]["request"]
        self.assertEqual(set(request["properties"]),
            {"project_dir", "sources", "text_layers", "protected_regions"})
        self.assertFalse(request["additionalProperties"])
        self.assertEqual(request["required"], ["sources", "text_layers"])
        sources = request["properties"]["sources"]
        self.assertEqual((sources["minItems"], sources["maxItems"]), (1, 9))
        self.assertEqual(set(sources["items"]["required"]), {"ref", "path", "sha256"})
        self.assertFalse(sources["items"]["additionalProperties"])
        self.assertEqual(sources["items"]["properties"]["sha256"]["pattern"], "^[a-f0-9]{64}$")
        layer = request["properties"]["text_layers"]["items"]
        self.assertFalse(layer["additionalProperties"])
        self.assertEqual(layer["properties"]["id"]["pattern"], "^[A-Za-z0-9_-]{1,80}$")
        rect = layer["properties"]["allowed_rect"]
        self.assertEqual(set(rect["required"]), {"x", "y", "width", "height"})
        self.assertFalse(rect["additionalProperties"])
        for key in ("width", "height"):
            self.assertEqual(rect["properties"][key]["exclusiveMinimum"], 0)
        self.assertEqual(request["properties"]["protected_regions"]["items"], rect)
        self.assertTrue(value["raw"]["ok"])
        self.assertEqual(value["raw"]["external_requests"], 0)
        png = Path(value["raw"]["png_path"])
        self.assertEqual(hashlib.sha256(png.read_bytes()).hexdigest(), value["raw"]["png_sha256"])
        with Image.open(png) as image:
            self.assertEqual(image.size, (1776, 2368))
        manifest = json.loads(Path(value["raw"]["manifest_path"]).read_bytes())
        self.assertEqual([box["text"] for box in manifest["checks"]["boxes"]],
            ["原照独立图层\n中文排字测试"])
        self.assertNotIn("approved_titles", manifest["constraints"])
        self.assertEqual((self.fixture.project / "assets/synthetic-photo.png").read_bytes(), self.fixture.photo)

    def test_omitted_project_directory_renders_the_actual_job_root(self):
        value = self.actual_host(root_project=True)
        self.assertNotIn("project_dir", value["schema"]["properties"]["request"]["required"])
        self.assertTrue(value["raw"]["ok"])
        self.assertEqual(value["raw"]["external_requests"], 0)
        self.assertEqual((self.fixture.directory / "assets/synthetic-photo.png").read_bytes(), self.fixture.photo)
        with Image.open(value["raw"]["png_path"]) as image:
            self.assertEqual(image.size, (1776, 2368))

    def test_direct_callback_extra_field_rejected_by_actual_cli_and_retained(self):
        # Direct callback is the internal/legacy defense; SDK validation of this
        # same extra key is covered by the actual SDK schema regression.
        value = self.actual_host(change=lambda request: request.update(unexpected_canvas=True))
        self.assertFalse(value["schema"]["properties"]["request"]["additionalProperties"])
        self.assertEqual(value["raw"]["code"], "REQUEST_FIELDS_FORBIDDEN")
        self.assertEqual(value["checkpoint"]["last_render_rejection"],
            {"code": "REQUEST_FIELDS_FORBIDDEN", "model_requests": 0})
        self.assertEqual(list((self.fixture.directory / "revisions").glob("*/out/poster.png")), [])

    def test_schema_valid_layer_mismatch_retains_actual_browser_code(self):
        value = self.actual_host(change=lambda request: request["text_layers"][0].update(id="absent-title"))
        self.assertEqual(value["raw"]["code"], "RENDER_FAILED")
        self.assertEqual(value["raw"]["detail"], "VISIBLE_TEXT_NOT_REGISTERED")
        self.assertEqual(value["checkpoint"]["last_render_rejection"],
            {"code": "VISIBLE_TEXT_NOT_REGISTERED", "model_requests": 0})
        self.assertEqual(list((self.fixture.directory / "revisions").glob("*/out/poster.png")), [])

    def test_source_hash_constraint_still_rejects_changed_manifest(self):
        value = self.actual_host(change=lambda request: request["sources"][0].update(sha256="0" * 64))
        self.assertEqual(value["raw"]["code"], "SOURCE_HASH_MISMATCH")
        self.assertEqual(value["checkpoint"]["last_render_rejection"],
            {"code": "SOURCE_HASH_MISMATCH", "model_requests": 0})
        self.assertEqual((self.fixture.project / "assets/synthetic-photo.png").read_bytes(), self.fixture.photo)
        self.assertEqual(list((self.fixture.directory / "revisions").glob("*/out/poster.png")), [])


if __name__ == "__main__":
    unittest.main()
