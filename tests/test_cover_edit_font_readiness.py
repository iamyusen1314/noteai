"""Real offline CLI regression for a newly used unicode-range font after edit."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from tests import test_cover_agent_artifacts as artifact_tests


class CoverEditFontReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = artifact_tests.AgentTitleCLIContractTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        html_path = f.project / "index.html"
        html = html_path.read_text().replace("原照独立图层<br>中文排字测试", "九篮现烤面包")
        css = ".title {position:absolute;left:120px;top:150px;width:1480px;height:260px;margin:0;font-family:var(--font-title);font-size:96px;line-height:1.18;font-weight:600;color:#203a34;white-space:pre-wrap}"
        replacement = ".title {position:absolute;left:936px;top:2150px;width:max-content;max-width:470px;height:46px;margin:0;font-family:var(--font-title);font-size:40px;line-height:46px;font-weight:600;letter-spacing:1px;color:#203a34;white-space:pre-wrap}"
        self.assertIn(css, html)
        html = html.replace(css, replacement)
        self.assertIn("noto-sans-sc-latin-wght-normal.woff2", html)
        self.assertRegex(html, r"unicode-range:\s*U\+0000-00FF")
        html_path.write_text(html)
        f.request["text_layers"] = [{"id": "title", "allowed_rect": {
            "x": 928, "y": 2144, "width": 470, "height": 60}}]
        f.request["approved_titles"] = ["九篮现烤面包"]
        self.trace = f.directory / "font-trace.jsonl"
        self.harness = f.directory / "delay-new-local-font.mjs"
        browser = f.model / "cover_editable/vendor/editable-design/scripts/_browser.mjs"
        # Only delay an existing local licensed font's request, leaving the
        # actual CLI request interception, font bytes and checks untouched.
        self.harness.write_text("""import fs from 'node:fs';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(pathToFileURL(BROWSER));
const puppeteer=(await import(pathToFileURL(require.resolve('puppeteer-core')))).default;
const log=(v)=>fs.appendFileSync(TRACE,JSON.stringify(v)+'\\n');
const launch=puppeteer.launch.bind(puppeteer);
puppeteer.launch=async(...args)=>{
 const browser=await launch(...args),newPage=browser.newPage.bind(browser);
 browser.newPage=async()=>{
  const page=await newPage(),on=page.on.bind(page),evaluate=page.evaluate.bind(page);
  let edited=false;
  page.evaluate=async(fn,...args)=>{
   if(typeof fn==='function'&&fn.toString().includes('delta.text'))edited=true;
   const result=await evaluate(fn,...args);
   if(result&&typeof result==='object'&&'fonts_status'in result){
    log({event:'actual_state',edited,fonts_status:result.fonts_status,
     images_loaded:result.images.every(x=>x.loaded),faces:result.font_faces,
     boxes:result.boxes.map(x=>({id:x.id,text:x.text,rect:x.rect,overflow:x.overflow}))});
   }
   return result;
  };
  page.on=(event,handler)=>{
   if(event!=='request')return on(event,handler);
   return on(event,(req)=>{
    if(edited&&req.url().endsWith('/noto-sans-sc-latin-wght-normal.woff2')){
     log({event:'new_local_subset_requested_after_edit',mode:MODE});
     if(MODE==='abort'){void req.abort('failed').catch(()=>{});return;}
     setTimeout(()=>{if(!page.isClosed())handler(req);},250);
    }else handler(req);
   });
  };
  return page;
 };
 return browser;
};
""".replace("BROWSER", json.dumps(str(browser))).replace("TRACE", json.dumps(str(self.trace))).replace("MODE", json.dumps("delay")))

    def edited(self, parent, text, *, mode="delay", expected_code=None):
        harness = self.harness
        if mode != "delay":
            harness = self.fixture.directory / "abort-new-local-font.mjs"
            harness.write_text(self.harness.read_text().replace('"delay"', '"abort"'))
        request = {"schema_version": self.fixture.request["schema_version"],
            "output_root": self.fixture.request["output_root"],
            "parent_revision_dir": parent["revision_dir"],
            "expected_parent_manifest_sha256": parent["manifest_sha256"],
            "edits": [{"layer_id": "title", "text": text}], "initial_qc_ref": "offline-initial-qc"}
        response = self.fixture.local([self.fixture.node, "--import", str(harness),
            str(self.fixture.cli), "edit"], body=json.dumps(request, ensure_ascii=False).encode())
        value = json.loads(response.stdout)
        if expected_code:
            self.assertNotEqual(response.returncode, 0)
            self.assertFalse(value["ok"])
            self.assertEqual(value["code"], expected_code, value)
        else:
            if response.returncode and self.trace.exists():
                print("COVER_EDIT_FONT_LOADING_OBSERVATION=" + json.dumps({"response": value,
                    "events": [json.loads(line) for line in self.trace.read_text().splitlines()]}, sort_keys=True))
            self.assertEqual(response.returncode, 0, value)
            self.assertTrue(value["ok"], value)
        return value

    def test_actual_cli_new_glyph_waits_for_font_and_keeps_dependency_and_geometry_checks(self):
        f = self.fixture
        parent = f.invoke("render", f.request)
        parent_png = Path(parent["png_path"]).read_bytes()
        parent_manifest = Path(parent["manifest_path"]).read_bytes()
        expected_sources = {x["ref"]: x["sha256"] for x in f.request["sources"]}
        _, bundle, original_layout = artifact_tests.artifacts.capture(parent, expected_sources=expected_sources)
        restored = artifact_tests.artifacts.restore(bundle, f.directory / "restored")
        parent = {**parent, "revision_dir": str(restored)}
        edited = self.edited(parent, "九篮·现烤面包")
        events = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertTrue(any(x["event"] == "new_local_subset_requested_after_edit" for x in events))
        actual_states = [x for x in events if x["event"] == "actual_state" and x["edited"]]
        self.assertTrue(actual_states)
        self.assertTrue(all(x["fonts_status"] == "loaded" and x["images_loaded"] for x in actual_states))
        manifest = json.loads(Path(edited["manifest_path"]).read_bytes())
        self.assertEqual(manifest["constraints"], json.loads(parent_manifest)["constraints"])
        self.assertEqual(manifest["checks"]["boxes"][0]["text"], "九篮·现烤面包")
        final, _, layout = artifact_tests.artifacts.capture(edited, expected_sources=expected_sources)
        self.assertEqual(hashlib.sha256(final).hexdigest(), edited["png_sha256"])
        self.assertEqual(layout["source_hashes"], original_layout["source_hashes"])
        self.assertEqual(layout["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
        self.edited(parent, "九篮·现烤面包", mode="abort", expected_code="OFFLINE_RENDER_ERROR")
        self.edited(parent, "九篮现烤面包" * 20, expected_code="TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION")
        self.assertEqual((restored / "out/poster.png").read_bytes(), parent_png)
        self.assertEqual((restored / "render-manifest.json").read_bytes(), parent_manifest)
        self.assertEqual((restored / "assets/synthetic-photo.png").read_bytes(), f.photo)
        print("COVER_EDIT_FONT_READINESS_PROOF=" + json.dumps({
            "actual_CLI_and_browser": True, "licensed_local_unicode_subset": True,
            "new_glyph_after_edit_requested_new_font": True,
            "font_loading_completed_before_geometry_state": True,
            "bundle_capture_restore_edit_PNG": True, "missing_font_still_rejected": True,
            "geometry_and_constraints_preserved": True, "parent_revision_unchanged": True,
            "external_requests": 0, "model_calls": 0, "merchant_quality_acceptance": False}, sort_keys=True))
