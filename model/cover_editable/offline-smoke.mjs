#!/usr/bin/env node
// Technical fixtures only: no merchant material, model or final-cover design.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { deflateSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';
const root = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: offline-smoke.mjs NEW_EVIDENCE_DIRECTORY');
await fs.mkdir(out, { recursive: false });
const project = path.join(out, 'project'); await fs.mkdir(path.join(project, 'assets'), { recursive: true });
const hash = (b) => createHash('sha256').update(b).digest('hex');
function crc32(b) { let c = 0xffffffff; for (const x of b) { c ^= x; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return (c ^ 0xffffffff) >>> 0; }
function chunk(t, b) { const kind = Buffer.from(t); const n = Buffer.alloc(4), c = Buffer.alloc(4); n.writeUInt32BE(b.length); c.writeUInt32BE(crc32(Buffer.concat([kind, b]))); return Buffer.concat([n, kind, b, c]); }
function syntheticPhoto() {
  const w = 800, h = 1000, pixels = Buffer.alloc(h * (1 + 3 * w));
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * (1 + 3 * w) + 1 + 3 * x;
    const subject = ((x - 400) / 220) ** 2 + ((y - 470) / 310) ** 2 < 1;
    pixels[i] = subject ? 215 : Math.round(80 + 100 * x / w);
    pixels[i + 1] = subject ? 180 : Math.round(90 + 85 * y / h);
    pixels[i + 2] = subject ? 105 : 120;
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(w); header.writeUInt32BE(h, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
}
const photo = syntheticPhoto(); await fs.writeFile(path.join(project, 'assets/synthetic-photo.png'), photo);
await fs.writeFile(path.join(project, 'poster.json'), JSON.stringify({ canvas: { width: 1776, height: 2368 }, scale: 1, dpi: null }, null, 2));
await fs.writeFile(path.join(project, 'index.html'), `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>离线技术夹具</title><style>
:root { --ink:#203a34; --field:#f6f2e9; --font-title:sans-serif; --font-body:serif; --font-label:sans-serif; }
* {box-sizing:border-box} html,body {margin:0;padding:0} .poster {position:relative;width:1776px;height:2368px;overflow:hidden;background:var(--field)}
.photo {position:absolute;left:120px;top:520px;width:1536px;height:1440px;object-fit:contain}
.title {position:absolute;left:120px;top:150px;width:1480px;height:260px;margin:0;font-family:var(--font-title);font-size:96px;line-height:1.18;font-weight:600;color:var(--ink);white-space:pre-wrap}
.caption {position:absolute;left:120px;top:2050px;width:1480px;height:80px;margin:0;font-family:var(--font-body);font-size:44px;line-height:1.3;font-weight:400;color:var(--ink)}
.label {position:absolute;left:120px;top:2190px;width:1480px;height:60px;margin:0;font-family:var(--font-label);font-size:38px;line-height:1.2;font-weight:400;color:var(--ink)}
</style></head><body><main class="poster" data-canvas-width="1776" data-canvas-height="2368"><img class="photo" data-layer-id="source-photo" src="assets/synthetic-photo.png" alt="合成原照技术夹具"><h1 class="title hf-slot" data-layer-id="title">原照独立图层\n中文排字测试</h1><p class="caption hf-slot" data-layer-id="caption">仅验证渲染合同，不是商家封面</p><p class="label hf-slot" data-layer-id="label">OFFLINE FIXTURE</p></main></body></html>`);
for (const id of ['cjk-sans', 'cjk-serif', 'clean-sans']) {
  const r = spawnSync(process.execPath, [path.join(root, 'vendor/editable-design/scripts/font-kit.mjs'), 'add', id, path.join(project, 'index.html')], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr);
}
const withFonts = (await fs.readFile(path.join(project, 'index.html'), 'utf8')).replace('--font-title:sans-serif', '--font-title:var(--font-kit-cjk-sans)').replace('--font-body:serif', '--font-body:var(--font-kit-cjk-serif)').replace('--font-label:sans-serif', '--font-label:var(--font-kit-clean-sans)');
await fs.writeFile(path.join(project, 'index.html'), withFonts);
const request = { schema_version: 'noteai-cover-editable/v1', project_dir: project, output_root: path.join(out, 'revisions'), sources: [{ ref: 'synthetic-source-1', path: 'assets/synthetic-photo.png', sha256: hash(photo) }], text_layers: [{ id: 'title', allowed_rect: { x: 96, y: 120, width: 1584, height: 320 } }, { id: 'caption', allowed_rect: { x: 96, y: 2020, width: 1584, height: 140 } }, { id: 'label', allowed_rect: { x: 96, y: 2160, width: 1584, height: 150 } }], protected_regions: [{ x: 430, y: 780, width: 900, height: 1000 }] };
const results = [];
async function invoke(name, command, body, expected = null) {
  await fs.writeFile(path.join(out, name + '.request.json'), JSON.stringify(body, null, 2));
  const r = spawnSync(process.execPath, [path.join(root, 'cli.mjs'), command], { input: JSON.stringify(body), encoding: 'utf8', timeout: 180000, maxBuffer: 8 * 1024 * 1024 });
  let value; try { value = JSON.parse(r.stdout); } catch { throw new Error(r.stdout + '\n' + r.stderr); }
  await fs.writeFile(path.join(out, name + '.result.json'), JSON.stringify(value, null, 2));
  if (expected ? value.code !== expected : !value.ok) throw new Error(name + ': ' + JSON.stringify(value));
  results.push({ name, ok: true, result: value }); console.log(name + ': PASS'); return value;
}
const base = await invoke('render-single', 'render', request);
const originalPNG = await fs.readFile(base.png_path);
const editRequest = { schema_version: request.schema_version, output_root: request.output_root, parent_revision_dir: base.revision_dir, expected_parent_manifest_sha256: base.manifest_sha256, initial_qc_ref: 'offline-fixture:NO_VISUAL_QC', edits: [{ layer_id: 'title', text: '免费修改文字\n断行与移位', dx: 20, dy: 12 }] };
const edited = await invoke('free-edit', 'edit', editRequest);
if (hash(await fs.readFile(base.png_path)) !== hash(originalPNG) || base.png_sha256 === edited.png_sha256) throw new Error('immutable/versioned image contract failed');
if (edited.qc_status !== 'USER_ADJUSTED_NOT_VISUALLY_REVIEWED') throw new Error('derived QC incorrectly inherited');
await invoke('edit-outside-zone', 'edit', { ...editRequest, edits: [{ layer_id: 'title', dx: 900, dy: 0 }] }, 'TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION');
await invoke('edit-stale-parent', 'edit', { ...editRequest, expected_parent_manifest_sha256: '0'.repeat(64) }, 'PARENT_REVISION_CONFLICT');
await invoke('edit-photo-forbidden', 'edit', { ...editRequest, edits: [{ layer_id: 'source-photo', text: 'forbidden' }] }, 'EDIT_FIELDS_FORBIDDEN');
await invoke('source-hash-mismatch', 'render', { ...request, sources: [{ ...request.sources[0], sha256: '0'.repeat(64) }] }, 'SOURCE_HASH_MISMATCH');
await invoke('text-over-protected-subject', 'render', { ...request, protected_regions: [{ x: 100, y: 100, width: 1500, height: 400 }] }, 'TEXT_OVER_PROTECTED_SUBJECT');
const hostile = path.join(out, 'external-project');
await fs.cp(project, hostile, { recursive: true });
const hostileHTML = (await fs.readFile(path.join(hostile, 'index.html'), 'utf8')).replace('src="assets/synthetic-photo.png"', 'src="https://example.invalid/never-request.png"');
await fs.writeFile(path.join(hostile, 'index.html'), hostileHTML);
await invoke('remote-image-rejected-before-browser', 'render', { ...request, project_dir: hostile }, 'EXTERNAL_OR_ABSOLUTE_RESOURCE_FORBIDDEN');
const changedParent = path.join(out, 'tampered-parent');
await fs.cp(base.revision_dir, changedParent, { recursive: true });
await fs.appendFile(path.join(changedParent, 'index.html'), '\n<!-- external change -->');
await invoke('parent-artifact-tamper', 'edit', { ...editRequest, parent_revision_dir: changedParent }, 'PARENT_ARTIFACT_CHANGED');
const nine = JSON.parse(JSON.stringify(request));
for (let i = 2; i <= 9; i++) { const rel = `assets/synthetic-${i}.png`; await fs.copyFile(path.join(project, 'assets/synthetic-photo.png'), path.join(project, rel)); nine.sources.push({ ref: `synthetic-source-${i}`, path: rel, sha256: hash(photo) }); }
const repeated = await invoke('render-nine-material-manifest', 'render', nine);
if (base.png_sha256 !== repeated.png_sha256) throw new Error('same authored source changed pixels across fresh renderer runs');
await fs.writeFile(path.join(out, 'evidence.json'), JSON.stringify({ scope: 'DETERMINISTIC_SYNTHETIC_FIXTURE_ONLY', model_calls: 0, merchant_photos: 0, visual_quality_acceptance: false, results, old_png_unchanged: true }, null, 2));
console.log(JSON.stringify({ ok: true, evidence: path.join(out, 'evidence.json'), checks: results.length, model_calls: 0 }));
