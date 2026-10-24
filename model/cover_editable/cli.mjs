#!/usr/bin/env node
/** NoteAI's local adapter around the complete pinned Editable-Design package.
 * The design agent authors the HTML. This adapter never plans or generates art.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { withBrowserTemporaryDirectory } from '../cover_agent_host/thumbnail.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.join(ROOT, 'vendor/editable-design');
const WIDTH = 1776, HEIGHT = 2368;
const SCHEMA = 'noteai-cover-editable/v1';
const MAX_BYTES = 150 * 1024 * 1024;
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const fail = (code, detail = '') => { throw Object.assign(new Error(detail || code), { code }); };
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const contained = (a, b) => b.x >= a.x - .5 && b.y >= a.y - .5 && b.x + b.width <= a.x + a.width + .5 && b.y + b.height <= a.y + a.height + .5;
const overlaps = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
function rect(v) {
  if (!v || !['x', 'y', 'width', 'height'].every((k) => finite(v[k])) || v.width <= 0 || v.height <= 0) fail('RECT_INVALID');
  return Object.fromEntries(['x', 'y', 'width', 'height'].map((k) => [k, v[k]]));
}
function relative(v) {
  if (typeof v !== 'string') fail('ASSET_PATH_INVALID');
  const normalized = v.replace(/^(?:\.\/)+/, '');
  if (!normalized || /[\\\0?#]/.test(normalized) || path.isAbsolute(normalized) || normalized.split('/').some((p) => !p || p === '.' || p === '..')) fail('ASSET_PATH_INVALID');
  return normalized;
}
async function json(file) { return JSON.parse(await fs.readFile(file, 'utf8')); }
async function writeJSON(file, value) { await fs.writeFile(file, JSON.stringify(value, null, 2) + '\n'); }
async function regular(file) { const st = await fs.lstat(file); if (!st.isFile() || st.isSymbolicLink()) fail('REGULAR_FILE_REQUIRED', file); return st; }
async function snapshot(source, target) {
  await fs.mkdir(target, { recursive: false });
  let total = 0;
  async function copy(from, to, prefix = '') {
    for (const ent of await fs.readdir(from, { withFileTypes: true })) {
      if (ent.isSymbolicLink()) fail('PROJECT_SYMLINK_FORBIDDEN');
      const rel = prefix + ent.name;
      if (!prefix && !['index.html', 'poster.json', 'assets', 'reference', 'brief.md', 'design-plan.md', 'asset-plan.json', 'prompts.md', 'render-review.md', 'cleanup-checklist.json'].includes(ent.name)) continue;
      const src = path.join(from, ent.name), dst = path.join(to, ent.name);
      if (ent.isDirectory()) { await fs.mkdir(dst); await copy(src, dst, rel + '/'); }
      else if (ent.isFile()) {
        if (!/\.(html|json|png|jpe?g|webp|woff2?|ttf|otf|txt|md)$/i.test(rel)) fail('ASSET_TYPE_FORBIDDEN', rel);
        const st = await regular(src); total += st.size;
        if (total > MAX_BYTES) fail('PROJECT_TOO_LARGE');
        await fs.copyFile(src, dst);
      } else fail('PROJECT_SPECIAL_FILE_FORBIDDEN');
    }
  }
  await copy(source, target);
}
function assertMarkup(html) {
  if (Buffer.byteLength(html) > 3 * 1024 * 1024) fail('HTML_TOO_LARGE');
  if (/<\s*(script|iframe|object|embed|base|link|form|input|audio|video)\b/i.test(html) || /\bon\w+\s*=/i.test(html) || /\bsrcset\s*=/i.test(html)) fail('ACTIVE_HTML_FORBIDDEN');
  if (/\b(?:src|href|xlink:href)\s*=\s*[^"'\s>]/i.test(html)) fail('RESOURCE_ATTRIBUTE_MUST_BE_QUOTED');
  if (/@import|javascript:|expression\s*\(/i.test(html)) fail('ACTIVE_CSS_FORBIDDEN');
  if (/@font-face\s*\{[^}]*\blocal\s*\(/i.test(html)) fail('SYSTEM_FONT_REFERENCE_FORBIDDEN');
  const refs = [...html.matchAll(/\b(?:src|href|xlink:href)\s*=\s*["']([^"']*)["']/gi)].map((m) => m[1]);
  refs.push(...[...html.matchAll(/url\(\s*["']?([^\)"']+)["']?\s*\)/gi)].map((m) => m[1].trim()));
  for (const ref of refs) {
    if (ref.startsWith('#')) continue;
    if (/[\\:]|^\/|%(?:2e|2f|5c)/i.test(ref)) fail('EXTERNAL_OR_ABSOLUTE_RESOURCE_FORBIDDEN', ref);
    relative(ref);
  }
  return refs.filter((r) => !r.startsWith('#')).map(relative);
}
const CSP = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src file:; font-src file:; style-src \'unsafe-inline\'; script-src \'none\'; connect-src \'none\'; base-uri \'none\'">';
async function freezeProject(dir, request) {
  const htmlPath = path.join(dir, 'index.html');
  let html = await fs.readFile(htmlPath, 'utf8');
  const refs = assertMarkup(html);
  for (const ref of refs) await regular(path.join(dir, ref));
  // A restrictive policy also covers escaped CSS URLs the static parser cannot interpret.
  if (!html.includes(CSP)) {
    if (!/<head\b[^>]*>/i.test(html)) fail('HTML_HEAD_REQUIRED');
    html = html.replace(/<head\b[^>]*>/i, (s) => s + '\n' + CSP);
    await fs.writeFile(htmlPath, html);
  }
  const config = await json(path.join(dir, 'poster.json'));
  if (config.canvas?.width !== WIDTH || config.canvas?.height !== HEIGHT || config.scale !== 1 || config.dpi) fail('CANVAS_MUST_BE_1776_2368_SCALE_1');
  if (!Array.isArray(request.sources) || !request.sources.length || request.sources.length > 9) fail('SOURCES_REQUIRED');
  const sources = [];
  const sourcePaths = new Set(), sourceRefs = new Set();
  for (const source of request.sources) {
    const rel = relative(source.path);
    if (!rel.startsWith('assets/') || !/\.(png|jpe?g|webp)$/i.test(rel) || !/^[a-f0-9]{64}$/.test(source.sha256) || typeof source.ref !== 'string' || !source.ref || sourcePaths.has(rel) || sourceRefs.has(source.ref)) fail('SOURCE_MANIFEST_INVALID');
    const bytes = await fs.readFile(path.join(dir, rel));
    if (sha(bytes) !== source.sha256) fail('SOURCE_HASH_MISMATCH', source.ref);
    sources.push({ ref: source.ref, path: rel, sha256: source.sha256 });
    sourcePaths.add(rel); sourceRefs.add(source.ref);
  }
  // The sole generated concept is a nonshipping reference. Shipping image files must be original-photo entries.
  for (const ref of refs) if (/\.(png|jpe?g|webp)$/i.test(ref) && !sourcePaths.has(ref)) fail('UNAUTHORIZED_SHIPPING_IMAGE', ref);
  if (!refs.some((ref) => sourcePaths.has(ref))) fail('SOURCE_PHOTO_NOT_USED');
  if (!Array.isArray(request.text_layers) || !request.text_layers.length) fail('TEXT_LAYERS_REQUIRED');
  const ids = new Set();
  const text_layers = request.text_layers.map((layer) => {
    if (!layer || !/^[A-Za-z0-9_-]{1,80}$/.test(layer.id) || ids.has(layer.id)) fail('TEXT_LAYER_ID_INVALID');
    ids.add(layer.id);
    return { id: layer.id, allowed_rect: rect(layer.allowed_rect) };
  });
  const protected_regions = (request.protected_regions || []).map(rect);
  return { sources, text_layers, protected_regions };
}
function run(command, args, cwd, name) {
  const started = performance.now();
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 120000, maxBuffer: 8 * 1024 * 1024, env: process.env });
  const evidence = { command: name, exit_code: result.status, signal: result.signal,
    elapsed_ms: Math.round(performance.now() - started),
    error: result.error ? { code: result.error.code, message: result.error.message } : null,
    stdout: result.stdout || '', stderr: result.stderr || '' };
  if (result.error || result.status !== 0) fail('UPSTREAM_' + name.toUpperCase() + '_FAILED', JSON.stringify(evidence));
  return evidence;
}
async function inspect(dir, manifest, edit = null, pngPath = null) {
  const { launch, open } = await import('./vendor/editable-design/scripts/_browser.mjs');
  const browser = await launch();
  const requests = [], blocked = [];
  const newPage = browser.newPage.bind(browser);
  browser.newPage = async () => {
    const page = await newPage();
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const url = req.url(); requests.push(url);
      let allowed = false;
      try { const f = fileURLToPath(url); allowed = f === dir || f.startsWith(dir + path.sep); } catch { /* blocked */ }
      if (allowed) req.continue(); else { blocked.push(url); req.abort(); }
    });
    return page;
  };
  try {
    const { page, errors } = await open(browser, path.join(dir, 'index.html'), { width: WIDTH, height: HEIGHT });
    if (edit) {
      await page.evaluate((deltas) => {
        for (const delta of deltas) {
          const el = [...document.querySelectorAll('[data-layer-id]')].find((e) => e.dataset.layerId === delta.layer_id);
          if (!el) throw new Error('EDIT_LAYER_MISSING');
          if (delta.text !== undefined) {
            if ([...el.children].some((child) => child.tagName !== 'BR')) throw new Error('EDIT_TEXT_REQUIRES_PLAIN_TEXT_LEAF');
            el.textContent = delta.text; el.style.whiteSpace = 'pre-wrap';
          }
          if (delta.dx || delta.dy) {
            const prior = getComputedStyle(el).translate.split(/\s+/).map(parseFloat);
            el.style.translate = `${(prior[0] || 0) + (delta.dx || 0)}px ${(prior[1] || 0) + (delta.dy || 0)}px`;
          }
        }
      }, edit);
      await fs.writeFile(path.join(dir, 'index.html'), await page.content());
    }
    const state = await page.evaluate(({ layers }) => {
      const canvas = document.querySelector('[data-canvas-width]');
      if (!canvas) throw new Error('CANVAS_MISSING');
      const c = canvas.getBoundingClientRect();
      if (Math.abs(c.width - 1776) > .5 || Math.abs(c.height - 2368) > .5) throw new Error('CANVAS_PIXEL_GEOMETRY_MISMATCH');
      const scaleX = c.width / Number(canvas.dataset.canvasWidth), scaleY = c.height / Number(canvas.dataset.canvasHeight);
      const textIDs = new Set(layers.map((layer) => layer.id));
      for (const el of [document.body, ...document.body.querySelectorAll('*')]) {
        const css = getComputedStyle(el), b = el.getBoundingClientRect();
        if (css.display === 'none' || css.visibility === 'hidden' || !b.width || !b.height) continue;
        for (const pseudo of ['::before', '::after']) {
          const content = getComputedStyle(el, pseudo).content;
          if (content && !['none', 'normal', '""', "''"].includes(content.trim())) throw new Error('GENERATED_TEXT_NOT_EDITABLE');
        }
      }
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.textContent.trim()) continue;
        const css = getComputedStyle(node.parentElement);
        if (css.display === 'none' || css.visibility === 'hidden') continue;
        const range = document.createRange(); range.selectNodeContents(node);
        if (![...range.getClientRects()].some((r) => r.width > 0 && r.height > 0)) continue;
        const owner = node.parentElement.closest('[data-layer-id]');
        if (!owner || !canvas.contains(owner) || !textIDs.has(owner.dataset.layerId)) throw new Error('VISIBLE_TEXT_NOT_REGISTERED');
      }
      const boxes = layers.map(({ id }) => {
        const found = [...canvas.querySelectorAll('[data-layer-id]')].filter((e) => e.dataset.layerId === id);
        if (found.length !== 1) throw new Error('TEXT_LAYER_NOT_UNIQUE:' + id);
        const el = found[0], b = el.getBoundingClientRect(), css = getComputedStyle(el);
        if ([...el.children].some((child) => child.tagName !== 'BR')) throw new Error('EDITABLE_LAYER_MUST_BE_TEXT_LEAF:' + id);
        const range = document.createRange(); range.selectNodeContents(el);
        const ink = [...range.getClientRects()].map((r) => ({ x: (r.x - c.x) / scaleX, y: (r.y - c.y) / scaleY, width: r.width / scaleX, height: r.height / scaleY }));
        const text = [...el.childNodes].map((node) => node.nodeName === 'BR' ? '\n' : node.textContent).join('');
        return { id, text, rect: { x: (b.x - c.x) / scaleX, y: (b.y - c.y) / scaleY, width: b.width / scaleX, height: b.height / scaleY }, ink, overflow: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1, font: css.fontFamily, font_size: css.fontSize, font_weight: css.fontWeight };
      });
      return { width: Number(canvas.dataset.canvasWidth), height: Number(canvas.dataset.canvasHeight), fonts_status: document.fonts.status, font_faces: [...document.fonts].map((f) => ({ family: f.family.replace(/["']/g, ''), weight: f.weight, status: f.status })), images: [...document.images].map((im) => {
        const b = im.getBoundingClientRect(), css = getComputedStyle(im);
        return { src: im.getAttribute('src'), layer_id: im.dataset.layerId || null, loaded: im.complete && im.naturalWidth > 0, natural_width: im.naturalWidth, natural_height: im.naturalHeight, rect: { x: (b.x - c.x) / scaleX, y: (b.y - c.y) / scaleY, width: b.width / scaleX, height: b.height / scaleY }, object_fit: css.objectFit, object_position: css.objectPosition };
      }), boxes };
    }, { layers: manifest.text_layers });
    if (errors.length || blocked.length) fail('OFFLINE_RENDER_ERROR', JSON.stringify({ errors, blocked }));
    if (state.width !== WIDTH || state.height !== HEIGHT || state.fonts_status !== 'loaded' || state.images.some((im) => !im.loaded)) fail('RENDER_DEPENDENCY_INCOMPLETE');
    for (const box of state.boxes) {
      const allowed = manifest.text_layers.find((l) => l.id === box.id).allowed_rect;
      const family = box.font.split(',')[0].trim().replace(/["']/g, '');
      if (!state.font_faces.some((f) => f.family === family && f.status === 'loaded')) fail('TEXT_FONT_NOT_SELF_HOSTED', box.id);
      if (box.overflow || !contained(allowed, box.rect) || box.ink.some((b) => !contained(allowed, b))) fail('TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION', JSON.stringify({
        id: box.id, element_rect: box.rect, allowed_rect: allowed, overflow: box.overflow,
        ink_rects: box.ink.slice(0, 16), ink_rect_count: box.ink.length }));
      if (manifest.protected_regions.some((r) => box.ink.some((b) => overlaps(r, b)))) fail('TEXT_OVER_PROTECTED_SUBJECT', box.id);
    }
    let screenshot = null;
    if (pngPath) {
      // Reuse the upstream pixelDiff capture pattern on the page just checked.
      // Element screenshots can wait for scrolling on a tall poster; clipping
      // the canvas also keeps page margins out of the delivered image.
      const canvas = await page.$('[data-canvas-width]');
      const clip = await canvas.boundingBox();
      if (!clip || ![clip.x, clip.y, clip.width, clip.height].every(finite)
          || clip.x < 0 || clip.y < 0) fail('CANVAS_NOT_CAPTURABLE');
      const started = performance.now();
      await page.screenshot({ path: pngPath, type: 'png', clip,
        captureBeyondViewport: true, omitBackground: false });
      if (errors.length || blocked.length) fail('OFFLINE_RENDER_ERROR', JSON.stringify({ errors, blocked }));
      screenshot = { renderer: 'editable_design_browser',
        upstream_module: 'scripts/_browser.mjs', operation: 'page.screenshot',
        elapsed_ms: Math.round(performance.now() - started), canvas_clip: clip,
        device_scale_factor: 1, external_requests: 0 };
    }
    return { ...state, ...(screenshot ? { screenshot } : {}), external_requests: 0, requested_local_files: [...new Set(requests.map((url) => path.relative(dir, fileURLToPath(url))))].sort(), visual_qc: 'NOT_PERFORMED' };
  } finally { await browser.close(); }
}
async function filesEvidence(dir) {
  const out = [];
  async function walk(current) {
    for (const ent of await fs.readdir(current, { withFileTypes: true })) {
      const file = path.join(current, ent.name);
      if (ent.isDirectory()) await walk(file);
      else if (ent.isFile() && !['render-manifest.json', 'render-result.json'].includes(ent.name)) { const bytes = await fs.readFile(file); out.push({ path: path.relative(dir, file), bytes: bytes.length, sha256: sha(bytes) }); }
    }
  }
  await walk(dir); return out.sort((a, b) => a.path.localeCompare(b.path));
}
async function perform(command, request) {
  if (request.schema_version !== SCHEMA) fail('SCHEMA_VERSION_INVALID');
  const allowedKeys = command === 'edit'
    ? ['schema_version', 'output_root', 'parent_revision_dir', 'expected_parent_manifest_sha256', 'edits', 'initial_qc_ref']
    : ['schema_version', 'output_root', 'project_dir', 'sources', 'text_layers', 'protected_regions', 'initial_qc_ref'];
  if (Object.keys(request).some((key) => !allowedKeys.includes(key))) fail('REQUEST_FIELDS_FORBIDDEN');
  const out = path.resolve(request.output_root || '');
  if (!request.output_root || !path.isAbsolute(request.output_root)) fail('ABSOLUTE_OUTPUT_ROOT_REQUIRED');
  await fs.mkdir(out, { recursive: true });
  let source, parent = null, effective = request;
  if (command === 'render') {
    if (!request.project_dir || !path.isAbsolute(request.project_dir)) fail('ABSOLUTE_PROJECT_DIR_REQUIRED');
    source = await fs.realpath(request.project_dir);
  } else if (command === 'edit') {
    source = await fs.realpath(request.parent_revision_dir);
    const raw = await fs.readFile(path.join(source, 'render-manifest.json'));
    if (sha(raw) !== request.expected_parent_manifest_sha256) fail('PARENT_REVISION_CONFLICT');
    parent = JSON.parse(raw);
    if (parent.schema_version !== SCHEMA || parent.status !== 'RENDERED') fail('PARENT_REVISION_INVALID');
    for (const file of parent.files) {
      const filename = path.join(source, relative(file.path));
      await regular(filename);
      if (sha(await fs.readFile(filename)) !== file.sha256) fail('PARENT_ARTIFACT_CHANGED', file.path);
    }
    effective = { ...parent.constraints, ...request };
    if (!Array.isArray(request.edits) || !request.edits.length || request.edits.length > 12) fail('EDITS_REQUIRED');
    const seen = new Set();
    for (const edit of request.edits) {
      if (!edit || Object.keys(edit).some((k) => !['layer_id', 'text', 'dx', 'dy'].includes(k)) || seen.has(edit.layer_id) || !parent.constraints.text_layers.some((l) => l.id === edit.layer_id)) fail('EDIT_FIELDS_FORBIDDEN');
      seen.add(edit.layer_id);
      if (edit.text !== undefined && (typeof edit.text !== 'string' || !edit.text.trim() || [...edit.text].length > 160 || /[\u0000-\u0008\u000b-\u001f]/.test(edit.text))) fail('EDIT_TEXT_INVALID');
      if (['dx', 'dy'].some((k) => edit[k] !== undefined && (!finite(edit[k]) || Math.abs(edit[k]) > WIDTH))) fail('EDIT_OFFSET_INVALID');
    }
  } else fail('COMMAND_INVALID');
  const id = randomUUID(), dir = path.join(out, id);
  await snapshot(source, dir);
  try {
    const constraints = await freezeProject(dir, effective);
    if (command === 'edit') await inspect(dir, constraints, request.edits);
    const evidence = [];
    evidence.push(run('/bin/bash', [path.join(SKILL, 'scripts/check-poster.sh'), path.join(dir, 'index.html')], dir, 'poster_contract'));
    evidence.push(run('/bin/bash', [path.join(SKILL, 'scripts/check-fonts.sh'), path.join(dir, 'index.html')], dir, 'fonts'));
    evidence.push(run(process.execPath, [path.join(SKILL, 'scripts/check-contract.mjs'), path.join(dir, 'index.html'), '--json'], dir, 'editable_contract'));
    await fs.mkdir(path.join(dir, 'out'));
    const checks = await inspect(dir, constraints, null, path.join(dir, 'out/poster.png'));
    evidence.push({ command: 'render', ...checks.screenshot });
    const png = await fs.readFile(path.join(dir, 'out/poster.png'));
    if (png.readUInt32BE(16) !== WIDTH || png.readUInt32BE(20) !== HEIGHT) fail('PNG_DIMENSION_MISMATCH');
    if (png.length > 10 * 1024 * 1024) fail('PNG_OUTPUT_TOO_LARGE');
    const manifest = { schema_version: SCHEMA, status: 'RENDERED', revision: id, parent_revision: parent?.revision || null, parent_manifest_sha256: command === 'edit' ? request.expected_parent_manifest_sha256 : null, created_at: new Date().toISOString(), constraints, edits: command === 'edit' ? request.edits : [], initial_qc_ref: request.initial_qc_ref || parent?.initial_qc_ref || null, qc_status: parent ? 'USER_ADJUSTED_NOT_VISUALLY_REVIEWED' : 'NOT_VISUALLY_REVIEWED', model_calls: 0, upstream_revision: 'c87b16f6d7c198e2b6967f13f1b1baa939d6f31f', checks, commands: evidence, files: await filesEvidence(dir) };
    await writeJSON(path.join(dir, 'render-manifest.json'), manifest);
    const manifestSHA = sha(await fs.readFile(path.join(dir, 'render-manifest.json')));
    const result = { ok: true, schema_version: SCHEMA, revision: id, revision_dir: dir, parent_revision: manifest.parent_revision, png_path: path.join(dir, 'out/poster.png'), png_sha256: sha(png), html_path: path.join(dir, 'index.html'), manifest_path: path.join(dir, 'render-manifest.json'), manifest_sha256: manifestSHA, width: WIDTH, height: HEIGHT, qc_status: manifest.qc_status, model_calls: 0, external_requests: 0 };
    await writeJSON(path.join(dir, 'render-result.json'), result);
    return result;
  } catch (error) {
    await writeJSON(path.join(dir, 'render-failure.json'), { code: error.code || 'RENDER_FAILED', detail: error.message, parent_revision: parent?.revision || null });
    throw error;
  }
}
try {
  const [command, flag, inputPath] = process.argv.slice(2);
  if (flag && flag !== '--input') fail('USAGE', 'cli.mjs render|edit [--input JSON_FILE]; otherwise read one JSON object from stdin');
  let body;
  if (flag) body = await fs.readFile(inputPath, 'utf8');
  else { const chunks = []; for await (const chunk of process.stdin) chunks.push(chunk); body = Buffer.concat(chunks).toString('utf8'); }
  if (Buffer.byteLength(body) > 1024 * 1024) fail('REQUEST_TOO_LARGE');
  process.stdout.write(JSON.stringify(await withBrowserTemporaryDirectory(() => perform(command, JSON.parse(body)))) + '\n');
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, schema_version: SCHEMA, code: error.code || 'RENDER_FAILED', detail: error.message, model_calls: 0 }) + '\n');
  process.exitCode = 1;
}
