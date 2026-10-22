#!/usr/bin/env node
/** Fixed OpenCode 2.1.2 host. Model transport and paid tools belong to Python.
 * stdout is a bidirectional JSON-lines protocol, never a diagnostic stream.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { makeThumbnail } from './thumbnail.mjs';

const MAX_LINE = 40 * 1024 * 1024;
const MAX_FILE = 10 * 1024 * 1024;
const sha = (value) => createHash('sha256').update(value).digest('hex');
const error = (code) => Object.assign(new Error(code), { code });
const send = (event) => process.stdout.write(JSON.stringify(event) + '\n');
const pending = new Map();
const localChildren = new Set();
let startResolve, startReject, inputClosed = false;
const startMessage = new Promise((resolve, reject) => { startResolve = resolve; startReject = reject; });
const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let receivedStart = false;
lines.on('line', (line) => {
  try {
    if (Buffer.byteLength(line) > MAX_LINE) throw error('PROTOCOL_LINE_TOO_LARGE');
    const value = JSON.parse(line);
    if (!receivedStart) {
      if (value.type !== 'start') throw error('START_REQUIRED');
      receivedStart = true; startResolve(value); return;
    }
    const waiter = pending.get(value.id);
    if (!waiter || !['model_response', 'tool_response'].includes(value.type)) throw error('UNEXPECTED_RESPONSE');
    pending.delete(value.id); clearTimeout(waiter.timer); waiter.resolve(value);
  } catch (e) {
    if (!receivedStart) startReject(e);
    else send({ type: 'protocol_error', code: e.code || 'INVALID_JSON' });
  }
});
lines.on('close', () => {
  inputClosed = true;
  if (!receivedStart) startReject(error('INPUT_CLOSED'));
  for (const { reject, timer } of pending.values()) { clearTimeout(timer); reject(error('BRIDGE_DISCONNECTED_UNKNOWN')); }
  pending.clear();
});
process.once('SIGTERM', () => {
  inputClosed = true;
  for (const child of localChildren) child.kill('SIGTERM');
  for (const { reject, timer } of pending.values()) { clearTimeout(timer); reject(error('HOST_TERMINATED_UNKNOWN')); }
  pending.clear(); process.exitCode = 143;
});

function inside(root, value) { return value === root || value.startsWith(root + path.sep); }
function relative(value) {
  if (typeof value !== 'string' || !value || path.isAbsolute(value) || /[\\\0]/.test(value) || value.split('/').some((part) => !part || part === '.' || part === '..')) throw error('RELATIVE_PATH_REQUIRED');
  return value;
}
async function safeExisting(root, value) {
  const target = await fs.realpath(path.resolve(root, relative(value)));
  if (!inside(root, target)) throw error('PATH_OUTSIDE_JOB');
  if (root === job?.work_dir && inside(job.state_dir, target)) throw error('HOST_STATE_FORBIDDEN');
  if (!(await fs.stat(target)).isFile()) throw error('REGULAR_FILE_REQUIRED');
  return target;
}
async function writeWithin(root, relativePath, text) {
  relative(relativePath);
  const parts = relativePath.split('/');
  if (parts.some((part) => part.startsWith('.')) || ['host-state', 'owner.json', 'noteai-input.json', 'host-session.json'].includes(parts[0]) || /^qc-\d+\.json$/.test(parts[0])) throw error('INTERNAL_PATH_FORBIDDEN');
  if (!/\.(html|json|md|txt)$/i.test(relativePath) || relativePath.startsWith('assets/') || Buffer.byteLength(text) > 3 * 1024 * 1024) throw error('WRITE_FILE_FORBIDDEN');
  const target = path.join(root, relativePath);
  if (inside(job.state_dir, target) || ['revisions', '.previews'].includes(relativePath.split('/')[0])) throw error('IMMUTABLE_OR_STATE_FILE');
  let directory = root;
  for (const part of relativePath.split('/').slice(0, -1)) {
    directory = path.join(directory, part);
    try { const st = await fs.lstat(directory); if (st.isSymbolicLink() || !st.isDirectory()) throw error('SYMLINK_FORBIDDEN'); }
    catch (e) { if (e.code !== 'ENOENT') throw e; await fs.mkdir(directory); }
  }
  if (!inside(root, await fs.realpath(path.dirname(target)))) throw error('PATH_OUTSIDE_JOB');
  try { if ((await fs.lstat(target)).isSymbolicLink()) throw error('SYMLINK_FORBIDDEN'); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (relativePath.endsWith('.html')) text = guardedHTML(text);
  await fs.writeFile(target, text); return { path: relativePath, bytes: Buffer.byteLength(text), sha256: sha(text) };
}
const CSP = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src file:; font-src file:; style-src \'unsafe-inline\'; script-src \'none\'; connect-src \'none\'; base-uri \'none\'">';
function guardedHTML(html) {
  if (/<\s*(script|iframe|object|embed|base|link|form|input|audio|video)\b/i.test(html) || /\bon\w+\s*=/i.test(html) || /\bsrcset\s*=|@import|javascript:|expression\s*\(/i.test(html)) throw error('ACTIVE_HTML_FORBIDDEN');
  if (/\b(?:src|href|xlink:href)\s*=\s*[^"'\s>]/i.test(html)) throw error('RESOURCE_MUST_BE_QUOTED');
  const refs = [...html.matchAll(/\b(?:src|href|xlink:href)\s*=\s*["']([^"']*)["']/gi)].map((m) => m[1]);
  refs.push(...[...html.matchAll(/url\(\s*["']?([^\)"']+)["']?\s*\)/gi)].map((m) => m[1].trim()));
  for (const ref of refs) { if (ref.startsWith('#')) continue; if (/[\\:]|^\/|%(?:2e|2f|5c)/i.test(ref)) throw error('EXTERNAL_RESOURCE_FORBIDDEN'); relative(ref.replace(/^(?:\.\/)+/, '')); }
  if (!/<head\b[^>]*>/i.test(html)) throw error('HTML_HEAD_REQUIRED');
  return html.includes(CSP) ? html : html.replace(/<head\b[^>]*>/i, (match) => match + '\n' + CSP);
}
async function atomicJSON(file, value) { await fs.writeFile(file + '.tmp', JSON.stringify(value, null, 2)); await fs.rename(file + '.tmp', file); }
function imageMime(file) { const ext = path.extname(file).toLowerCase(); const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }[ext]; if (!mime) throw error('IMAGE_FORMAT_FORBIDDEN'); return mime; }
async function imageFile(root, rel) {
  const file = await safeExisting(root, rel), bytes = await fs.readFile(file);
  if (bytes.length > MAX_FILE) throw error('IMAGE_TOO_LARGE');
  return { uri: `data:${imageMime(file)};base64,${bytes.toString('base64')}`, mime: imageMime(file), name: path.basename(file) };
}
async function runLocal(command, args, cwd, stdin = null) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env: process.env, stdio: ['pipe', 'pipe', 'pipe'] });
    localChildren.add(child);
    let stdout = '', stderr = '', size = 0;
    const timer = setTimeout(() => { child.kill('SIGTERM'); reject(error('LOCAL_TOOL_TIMEOUT')); }, 150000);
    child.on('error', (e) => { clearTimeout(timer); reject(e); });
    child.stdout.on('data', (part) => { size += part.length; if (size > 8 * 1024 * 1024) child.kill('SIGTERM'); else stdout += part; });
    child.stderr.on('data', (part) => { if (stderr.length < 100000) stderr += part; });
    child.on('close', (code) => { localChildren.delete(child); clearTimeout(timer); resolve({ code, stdout, stderr }); });
    child.stdin.end(stdin);
  });
}
function completionSSE(body) {
  const chunks = [];
  for (const choice of body.choices || []) {
    const message = choice.message || {};
    const delta = { role: message.role || 'assistant' };
    for (const key of ['content', 'reasoning_content', 'reasoning', 'tool_calls']) if (message[key] != null) delta[key] = key === 'tool_calls' ? message[key].map((call, index) => ({ index, ...call })) : message[key];
    chunks.push({ ...body, object: 'chat.completion.chunk', choices: [{ index: choice.index || 0, delta, finish_reason: null }], usage: undefined });
    chunks.push({ ...body, object: 'chat.completion.chunk', choices: [{ index: choice.index || 0, delta: {}, finish_reason: choice.finish_reason || 'stop' }], usage: undefined });
  }
  if (body.usage) chunks.push({ ...body, object: 'chat.completion.chunk', choices: [], usage: body.usage });
  return chunks.map((chunk) => 'data: ' + JSON.stringify(chunk) + '\n\n').join('') + 'data: [DONE]\n\n';
}
function objectSchema(properties, required = Object.keys(properties)) { return { type: 'object', properties, required, additionalProperties: false }; }

let sdk, server, job, checkpoint, checkpointPath, checkpointOwned = false, requests = 0, lastRender = null, lastPreview = null;
const hooks = [];
const originalFetch = globalThis.fetch;
try {
  job = await startMessage;
  job.mode ??= 'run';
  if (!['run', 'inspect', 'revise'].includes(job.mode)) throw error('START_MODE_INVALID');
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(job.job_id || '') || typeof job.prompt !== 'string' || typeof job.model_id !== 'string') throw error('START_FIELDS_INVALID');
  for (const key of ['state_dir', 'work_dir', 'skill_dir', 'editable_cli']) if (!path.isAbsolute(job[key] || '')) throw error('ABSOLUTE_START_PATH_REQUIRED');
  if (job.max_model_requests != null && (!Number.isSafeInteger(job.max_model_requests) || job.max_model_requests < 1)) throw error('INVALID_REQUEST_LIMIT');
  if (!Number.isFinite(job.deadline_epoch_ms) || job.deadline_epoch_ms <= Date.now()) throw error('VALID_DEADLINE_REQUIRED');
  await fs.mkdir(job.state_dir, { recursive: true }); await fs.mkdir(job.work_dir, { recursive: true });
  job.state_dir = await fs.realpath(job.state_dir); job.work_dir = await fs.realpath(job.work_dir); job.skill_dir = await fs.realpath(job.skill_dir); job.editable_cli = await fs.realpath(job.editable_cli);
  checkpointPath = path.join(job.state_dir, 'host-checkpoint.json');
  try { checkpoint = JSON.parse(await fs.readFile(checkpointPath, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (checkpoint && (checkpoint.job_id !== job.job_id || checkpoint.work_dir !== job.work_dir)) throw error('CHECKPOINT_JOB_MISMATCH');
  if (checkpoint?.pending_request || checkpoint?.pending_tool || checkpoint?.status === 'UNKNOWN') throw error('PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY');
  if (job.mode === 'revise' && (!checkpoint?.session_id || checkpoint.status !== 'COMPLETE' || job.session_id !== checkpoint.session_id || (checkpoint.revision_count || 0) >= 1)) throw error('REVISION_REQUIRES_KNOWN_COMPLETE_SESSION');
  if (checkpoint?.session_id && !['inspect', 'revise'].includes(job.mode)) throw error('EXISTING_SESSION_INSPECT_FIRST');
  requests = checkpoint?.model_requests || 0;
  lastRender = checkpoint?.artifact || null;
  lastPreview = checkpoint?.preview || null;
  checkpoint = { ...checkpoint, job_id: job.job_id, work_dir: job.work_dir, status: 'STARTING', model_requests: requests };
  await atomicJSON(checkpointPath, checkpoint);
  checkpointOwned = true;
  const home = path.join(job.state_dir, 'isolated');
  // Remove inherited provider credentials before importing any SDK module.
  for (const key of Object.keys(process.env)) if (!['PATH', 'TMPDIR', 'NOTEAI_COVER_HOST_NODE_MODULES', 'EDITABLE_DESIGN_BROWSER', 'PUPPETEER_EXECUTABLE_PATH', 'NO_SANDBOX', 'EDITABLE_DESIGN_NO_SANDBOX'].includes(key)) delete process.env[key];
  process.env.OPENCODE_TEST_HOME = home; process.env.OPENCODE_DISABLE_FREE_MODELS = 'true';
  for (const [key, leaf] of Object.entries({ XDG_DATA_HOME: 'data', XDG_CONFIG_HOME: 'config', XDG_CACHE_HOME: 'cache', XDG_STATE_HOME: 'state' })) { process.env[key] = path.join(home, leaf); await fs.mkdir(process.env[key], { recursive: true }); }
  process.env.NOTEAI_HOST_TOKEN = 'local-bridge-only';
  const modules = process.env.NOTEAI_COVER_HOST_NODE_MODULES;
  if (!modules || !path.isAbsolute(modules)) throw error('LOCAL_RUNTIME_MODULES_REQUIRED');
  for (const pkg of ['sdk', 'plugin']) if (JSON.parse(await fs.readFile(path.join(modules, `@opencode/${pkg}/package.json`), 'utf8')).version !== '2.1.2') throw error('SDK_VERSION_MISMATCH');
  const load = (rel) => import(pathToFileURL(path.join(modules, rel)).href);
  const bridge = async (type, fields) => {
    if (inputClosed) throw error('BRIDGE_DISCONNECTED_UNKNOWN');
    const id = randomUUID();
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(error('BRIDGE_TIMEOUT_UNKNOWN')); }, Math.max(1, job.deadline_epoch_ms - Date.now()));
      pending.set(id, { resolve, reject, timer }); send({ type, id, ...fields });
    });
  };
  server = http.createServer(async (req, res) => {
    let physical = false;
    try {
      if (req.method !== 'POST' || req.url !== '/v1/chat/completions') throw error('MODEL_ROUTE_FORBIDDEN');
      let raw = ''; for await (const chunk of req) { raw += chunk; if (Buffer.byteLength(raw) > MAX_LINE) throw error('MODEL_REQUEST_TOO_LARGE'); }
      const body = JSON.parse(raw), wasStream = body.stream === true;
      if (job.mode === 'inspect') throw error('INSPECT_FORBIDS_MODEL_CALL');
      if (checkpoint.status === 'UNKNOWN' || checkpoint.pending_tool) throw error('PREVIOUS_TOOL_UNKNOWN_NO_CONTINUATION');
      if (Date.now() >= job.deadline_epoch_ms || (job.max_model_requests != null && requests >= job.max_model_requests)) throw error('MODEL_REQUEST_LIMIT');
      body.stream = false; delete body.stream_options;
      if (body.model !== job.model_id) throw error('MODEL_ID_NOT_LOCKED');
      requests += 1; physical = true;
      checkpoint = { ...checkpoint, model_requests: requests, status: 'AWAITING_MODEL', pending_request: { ordinal: requests, body_sha256: sha(JSON.stringify(body)), label: hooks.at(-1)?.kind || 'unknown' } };
      await atomicJSON(checkpointPath, checkpoint);
      const answer = await bridge('model_request', { ordinal: requests, label: checkpoint.pending_request.label, method: 'POST', path: '/chat/completions', body });
      if (answer.unknown) throw error('SUPPLIER_RESULT_UNKNOWN');
      if (!Number.isInteger(answer.status) || answer.status < 100 || answer.status > 599) throw error('MODEL_RESPONSE_INVALID');
      const payload = typeof answer.body === 'string' ? answer.body : JSON.stringify(answer.body);
      checkpoint = { ...checkpoint, pending_request: null, status: answer.status >= 200 && answer.status < 300 ? 'RUNNING' : 'FAILED', last_response_status: answer.status };
      await atomicJSON(checkpointPath, checkpoint);
      let output = payload, contentType = 'application/json';
      if (wasStream && answer.status >= 200 && answer.status < 300) { output = completionSSE(JSON.parse(payload)); contentType = 'text/event-stream'; }
      res.writeHead(answer.status, { 'content-type': contentType }); res.end(output);
    } catch (e) {
      if (physical && checkpoint.pending_request) { checkpoint.status = 'UNKNOWN'; await atomicJSON(checkpointPath, checkpoint); }
      res.writeHead(502, { 'content-type': 'application/json' }); res.end(JSON.stringify({ error: { message: e.code || 'HOST_TRANSPORT_FAILED', type: 'noteai_host' } }));
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const baseURL = `http://127.0.0.1:${server.address().port}/v1`;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    if (url.hostname !== '127.0.0.1' || url.port !== String(server.address().port)) throw error('HOST_NETWORK_DENIED');
    return originalFetch(input, init);
  };
  const { create } = await load('@opencode/sdk/dist/promise.js');
  const { Plugin } = await load('@opencode/plugin/dist/promise/index.js');
  const { Config } = await load('@opencode/core/dist/config.js');
  const { Global } = await load('@opencode/util/dist/global.js');
  const fullSkill = await fs.readFile(path.join(job.skill_dir, 'SKILL.md'), 'utf8');
  const skillsSha = sha(fullSkill);
  // SDK tool calls may arrive in parallel. One local tool owns files and
  // browser capacity through its entire render/check/thumbnail operation.
  let localToolTail = Promise.resolve();
  const tool = (name, description, input, execute) => ({ name, description, input, options: { codemode: false }, execute: async (args) => {
    const previous = localToolTail;
    let release;
    localToolTail = new Promise((resolve) => { release = resolve; });
    await previous;
    try {
      if (inputClosed || Date.now() >= job.deadline_epoch_ms) throw error('LOCAL_TOOL_DEADLINE');
      return await execute(args);
    } catch (e) {
      if (/UNKNOWN/.test(e.code || '')) { checkpoint.status = 'UNKNOWN'; await atomicJSON(checkpointPath, checkpoint); }
      return { content: JSON.stringify({ ok: false, code: e.code || 'LOCAL_TOOL_FAILED', detail: e.message }) };
    } finally { release(); }
  } });
  const tools = [
    tool('cover_read', 'Read a UTF-8 job file, or a complete Skill reference using skill:relative/path. Images use cover_view.', objectSchema({ path: { type: 'string' } }), async ({ path: rel }) => {
      const fromSkill = rel.startsWith('skill:'); const file = await safeExisting(fromSkill ? job.skill_dir : job.work_dir, fromSkill ? rel.slice(6) : rel);
      if (!/\.(md|txt|json|html|css|ya?ml|mjs|js|sh)$/i.test(file)) throw error('READ_FORMAT_FORBIDDEN');
      const bytes = await fs.readFile(file); if (bytes.length > 1024 * 1024) throw error('READ_TOO_LARGE'); return { content: bytes.toString('utf8') };
    }),
    tool('cover_write', 'Write a complete local HTML/JSON/Markdown/text design file within this job. No scripts or source asset changes.', objectSchema({ path: { type: 'string' }, text: { type: 'string' } }), async ({ path: rel, text }) => ({ content: JSON.stringify(await writeWithin(job.work_dir, rel, text)) })),
    tool('cover_view', 'Inspect actual local photo, concept, or render pixels. Viewing the last final PNG also includes its actual 240x320 preview. Result images go to the next model request.', objectSchema({ path: { type: 'string' } }), async ({ path: rel }) => {
      const content = [{ type: 'file', ...await imageFile(job.work_dir, rel) }];
      if (lastRender && lastPreview && path.resolve(job.work_dir, rel) === lastRender.png_path) content.push({ type: 'file', ...await imageFile(job.work_dir, path.relative(job.work_dir, lastPreview.path)) });
      return { content };
    }),
    tool('cover_seedream', 'Request the single nonshipping composition concept using the approved original photos. Python supplies the authorized photos, checks budget, facts and call state, and saves the result locally. Never use concept pixels in final artwork.', objectSchema({ prompt: { type: 'string' } }), async (args) => {
      if (checkpoint.pending_tool || checkpoint.concept_requested) throw error('CONCEPT_ALREADY_REQUESTED');
      checkpoint.concept_requested = true;
      checkpoint.pending_tool = { name: 'cover_seedream', prompt_sha256: sha(args.prompt) }; await atomicJSON(checkpointPath, checkpoint);
      const answer = await bridge('tool_request', { name: 'cover_seedream', arguments: args });
      if (answer.unknown) throw error('SUPPLIER_RESULT_UNKNOWN');
      checkpoint.pending_tool = null; await atomicJSON(checkpointPath, checkpoint);
      return { content: JSON.stringify(answer.result) };
    }),
    tool('cover_render', 'Validate and render the authored project with the complete pinned Editable-Design renderer. Python must approve original and concept image inspection before execution.', objectSchema({ request: { type: 'object', additionalProperties: true } }), async ({ request }) => {
      request = { ...request, schema_version: 'noteai-cover-editable/v1', output_root: path.join(job.work_dir, 'revisions') };
      request.project_dir = path.resolve(job.work_dir, request.project_dir || 'project');
      if (!inside(job.work_dir, await fs.realpath(request.project_dir))) throw error('PATH_OUTSIDE_JOB');
      const answer = await bridge('tool_request', { name: 'cover_render', arguments: request });
      if (answer.result?.allowed !== true) throw error(answer.result?.code || 'RENDER_NOT_APPROVED');
      const run = await runLocal(process.execPath, [job.editable_cli, 'render'], request.project_dir, JSON.stringify(request));
      let result; try { result = JSON.parse(run.stdout); } catch { throw error('RENDER_RESPONSE_INVALID'); }
      if (run.code !== 0 || result.ok !== true) return { content: JSON.stringify(result) };
      lastRender = result; checkpoint.artifact = result; await atomicJSON(checkpointPath, checkpoint);
      lastPreview = await makeThumbnail({ pngPath: result.png_path, outputRoot: path.join(job.work_dir, '.previews'), skillDir: job.skill_dir });
      checkpoint.preview = lastPreview; await atomicJSON(checkpointPath, checkpoint);
      const forAgent = { ...result };
      for (const key of ['png_path', 'html_path', 'manifest_path', 'revision_dir']) if (typeof forAgent[key] === 'string' && inside(job.work_dir, forAgent[key])) forAgent[key] = path.relative(job.work_dir, forAgent[key]);
      forAgent.image_path = forAgent.png_path;
      forAgent.thumbnail_path = path.relative(job.work_dir, lastPreview.path); forAgent.thumbnail_sha256 = lastPreview.sha256;
      send({ type: 'render_finished', artifact: result, preview: lastPreview }); return { content: JSON.stringify(forAgent) };
    }),
    tool('cover_check', 'Run only the pinned local Skill poster/font/contract checks, or install a preinstalled font. No shell commands or downloads. font_add must precede any var(--font-kit-ID) reference.', objectSchema({ action: { type: 'string', enum: ['poster', 'fonts', 'contract', 'font_add'] }, html: { type: 'string' }, font_id: { type: 'string' } }, ['action', 'html']), async ({ action, html, font_id }) => {
      const file = await safeExisting(job.work_dir, html); if (!file.endsWith('.html')) throw error('HTML_REQUIRED');
      if (action === 'font_add' && inside(path.join(job.work_dir, 'revisions'), file)) throw error('IMMUTABLE_REVISION');
      await fs.writeFile(file, guardedHTML(await fs.readFile(file, 'utf8')));
      const scripts = path.join(job.skill_dir, 'scripts');
      const commands = { poster: ['/bin/bash', [path.join(scripts, 'check-poster.sh'), file]], fonts: ['/bin/bash', [path.join(scripts, 'check-fonts.sh'), file]], contract: [process.execPath, [path.join(scripts, 'check-contract.mjs'), file, '--json']] };
      if (action === 'font_add') {
        if (!['editorial-serif', 'luxury-serif', 'clean-sans', 'geometric-sans', 'condensed-sans', 'experimental-display', 'cjk-sans', 'cjk-serif', 'cjk-calligraphy', 'cjk-display'].includes(font_id)) throw error('FONT_ID_FORBIDDEN');
        commands.font_add = [process.execPath, [path.join(scripts, 'font-kit.mjs'), 'add', font_id, file]];
      }
      const [cmd, args] = commands[action]; return { content: JSON.stringify(await runLocal(cmd, args, path.dirname(file))) };
    }),
  ];
  const allowedTools = new Set(tools.map((item) => item.name));
  const permissions = [{ action: '*', resource: '*', effect: 'deny' }, ...tools.map((item) => ({ action: item.name, resource: '*', effect: 'allow' }))];
  const plugin = Plugin.define({ id: 'noteai-cover-boundary-v1', async setup(ctx) {
    await ctx.skill.transform((editor) => { for (const item of editor.list()) editor.remove(item.id); editor.add({ id: 'editable-design', name: 'editable-design', path: path.join(job.skill_dir, 'SKILL.md'), description: 'Complete fixed Editable-Design workflow', content: fullSkill }); });
    await ctx.provider.transform((editor) => { for (const item of editor.list()) if (item.provider.id !== 'noteai') editor.remove(item.provider.id); });
    await ctx.tool.transform((editor) => { for (const item of editor.list()) editor.remove(item.id); for (const item of tools) editor.add(item); });
    await ctx.tool.hook('execute.before', (event) => { if (!allowedTools.has(event.tool)) throw error('TOOL_NOT_ALLOWED'); if (Date.now() >= job.deadline_epoch_ms) throw error('TOOL_DEADLINE'); });
    // A deterministic title needs no paid call. Any actual auxiliary generation
    // (including SDK compaction) shares this provider bridge and money ledger.
    await ctx.session.hook('title', (event) => { event.result = 'NoteAI cover ' + job.job_id; });
    await ctx.session.hook('http.request', (event) => {
      if (!event.request.url.startsWith(baseURL + '/')) throw error('PROVIDER_ROUTE_FORBIDDEN');
      hooks.push({ kind: event.kind, session_id: event.sessionID });
      send({ type: 'request_hook', kind: event.kind, session_id: event.sessionID });
    });
    await ctx.session.hook('retry', (event) => { event.decision = { retry: false }; send({ type: 'retry_veto', attempt: event.attempt, error_type: event.error.type }); });
  } });
  const config = { media: { image: { auto_resize: false, max_width: 36000000, max_height: 36000000, max_base64_bytes: Math.ceil(MAX_FILE / 3) * 4 } }, providers: { noteai: { activation: 'enabled', env: ['NOTEAI_HOST_TOKEN'], package: '@opencode/ai/providers/openai-compatible', settings: { baseURL, transport: 'http', encoding: 'none' }, models: { [job.model_id]: { capabilities: { input: ['text', 'image'], output: ['text'], tools: true }, limit: { context: job.context_tokens || 128000, output: job.output_tokens || 8192 } } } } }, model: 'noteai/' + job.model_id, skills: [], update: 'disable', permissions: [{ action: '*', resource: '*', effect: 'deny' }] };
  const cfg = { project: false, global: false, system: false, claude: false, content: JSON.stringify(config) };
  sdk = await create({ config: { project: false, claude: false, content: cfg.content }, database: { path: path.join(job.state_dir, 'session.sqlite') }, models: { fetch: false, snapshot: false }, fs: { filewatcher: false, fff: false }, plugins: [plugin], log: { level: 'error', emit: (e) => process.stderr.write(JSON.stringify({ sdk_log: e.level, message: e.message }) + '\n') } }, { overrides: [Global.node.replace(Global.layerWith({ home, data: path.join(home, 'data'), config: path.join(home, 'config'), cache: path.join(home, 'cache'), state: path.join(home, 'state'), tmp: path.join(home, 'tmp'), bin: path.join(home, 'bin'), log: path.join(home, 'log'), repos: path.join(home, 'repos') })), Config.node.replace(Config.configured(cfg))] });
  let session;
  if (['inspect', 'revise'].includes(job.mode)) {
    if (!checkpoint.session_id) throw error('NO_SESSION_TO_INSPECT');
    session = await sdk.sessions.get({ sessionID: checkpoint.session_id });
  } else {
    session = await sdk.sessions.create({ location: { directory: job.work_dir }, model: { providerID: 'noteai', id: job.model_id }, title: 'NoteAI cover ' + job.job_id, permissions });
  }
  checkpoint.session_id = session.id; checkpoint.status = 'RUNNING'; await atomicJSON(checkpointPath, checkpoint);
  send({ type: 'ready', session_id: session.id, sdk_version: '2.1.2', skill_sha256: skillsSha, model_requests: requests });
  if (job.mode !== 'inspect') {
    if (job.mode === 'revise') { checkpoint.revision_count = (checkpoint.revision_count || 0) + 1; await atomicJSON(checkpointPath, checkpoint); }
    const files = [];
    for (const image of job.images || []) files.push({ ...await imageFile(job.work_dir, image.path), ...(image.name ? { name: image.name } : {}) });
    await sdk.sessions.prompt({ sessionID: session.id, text: job.prompt, skills: [{ id: 'editable-design' }], files });
    await sdk.sessions.wait({ sessionID: session.id });
  }
  const context = await sdk.sessions.context({ sessionID: session.id });
  const last = context.at(-1);
  const failed = last?.type === 'idle' && last.outcome === 'failed';
  checkpoint.status = checkpoint.pending_request || checkpoint.pending_tool || checkpoint.status === 'UNKNOWN' ? 'UNKNOWN' : failed ? 'FAILED' : 'COMPLETE';
  checkpoint.model_requests = requests; checkpoint.artifact = lastRender; await atomicJSON(checkpointPath, checkpoint);
  const contextSummary = context.map((item) => ({ type: item.type, id: item.id, outcome: item.outcome, error: item.error, usage: item.usage, text: typeof item.text === 'string' ? item.text.slice(0, 4000) : undefined, files: item.files?.map((file) => ({ name: file.name, mime: file.mime, sha256: file.data ? sha(Buffer.from(file.data, 'base64')) : undefined })), skills: item.skills?.map((skill) => ({ id: skill.id, name: skill.name, sha256: sha(skill.text || '') })) }));
  send({ type: 'result', ok: !failed && checkpoint.status !== 'UNKNOWN', status: checkpoint.status, session_id: session.id, model_requests: requests, artifact: lastRender, preview: lastPreview, context: contextSummary });
} catch (e) {
  if (checkpoint && checkpointPath && checkpointOwned) { checkpoint.status = checkpoint.pending_request || checkpoint.pending_tool || checkpoint.status === 'UNKNOWN' ? 'UNKNOWN' : 'FAILED'; await atomicJSON(checkpointPath, checkpoint).catch(() => {}); }
  send({ type: 'result', ok: false, status: checkpoint?.status || 'FAILED', code: e.code || 'HOST_FAILED', detail: e.message, session_id: checkpoint?.session_id || null, model_requests: requests, artifact: lastRender }); process.exitCode = 1;
} finally {
  if (sdk) await sdk.close();
  if (server) await new Promise((resolve) => server.close(resolve));
  lines.close(); process.stdin.pause(); globalThis.fetch = originalFetch;
}
