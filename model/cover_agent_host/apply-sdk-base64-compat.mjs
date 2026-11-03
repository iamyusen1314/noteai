#!/usr/bin/env node
/** Build-only compatibility patch for the pinned OpenCode 2.1.2 schema.
 * Never edits an unknown dependency or evaluates an image/model request.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

const VERSION = '2.1.2';
const ORIGINAL_SHA256 = '2fd973e0fac2f8fe9025ced5a3ba410768ab99806143e70e4388044f27f325b4';
const PATCHED_SHA256 = '90e473112cca6e5cda43aceb63bddc1daa1adb028f96f1e7796896b52c410904';
const ANCHOR = 'export const Base64 = Schema.String.check(Schema.isPattern(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u)).annotate({ identifier: "Prompt.Base64" });';
const REPLACEMENT = `// NoteAI compatibility: validate the same Base64 language without RegExp stack growth.
function noteaiBase64IsValid(value) {
    const length = value.length;
    if (length % 4 !== 0) return false;
    let end = length;
    if (end && value.charCodeAt(end - 1) === 61) end--;
    if (end && value.charCodeAt(end - 1) === 61) end--;
    for (let i = 0; i < end; i++) {
        const c = value.charCodeAt(i);
        if (!(c >= 65 && c <= 90 || c >= 97 && c <= 122 ||
              c >= 48 && c <= 57 || c === 43 || c === 47)) return false;
    }
    return true;
}
// Retain the original filter annotations, including pattern representation,
// JSON Schema, expected text and arbitrary constraints. Its RegExp run is unused.
const noteaiBase64Pattern = Schema.isPattern(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u);
export const Base64 = Schema.String.check(Schema.makeFilter(noteaiBase64IsValid, noteaiBase64Pattern.annotations)).annotate({ identifier: "Prompt.Base64" });`;
const digest = (body) => createHash('sha256').update(body).digest('hex');
const fail = (code) => { throw Object.assign(new Error(code), { code }); };

async function regularFile(file) {
  const info = await fs.lstat(file);
  if (!info.isFile() || info.isSymbolicLink()) fail('SDK_BASE64_REGULAR_FILE_REQUIRED');
  return info;
}

async function apply(modules) {
  if (!modules || !path.isAbsolute(modules)) fail('SDK_BASE64_ABSOLUTE_MODULES_REQUIRED');
  for (const name of ['sdk', 'schema']) {
    const file = path.join(modules, '@opencode', name, 'package.json');
    await regularFile(file);
    const value = JSON.parse(await fs.readFile(file, 'utf8'));
    if (value.version !== VERSION) fail('SDK_BASE64_VERSION_MISMATCH');
  }
  const file = path.join(modules, '@opencode/schema/dist/prompt.js');
  const info = await regularFile(file);
  const before = await fs.readFile(file);
  const beforeSHA = digest(before);
  if (beforeSHA === PATCHED_SHA256) return { status: 'already_patched',
    sdk_version: VERSION, schema_version: VERSION, before_sha256: beforeSHA,
    after_sha256: beforeSHA, bytes: before.length };
  if (beforeSHA !== ORIGINAL_SHA256) fail('SDK_BASE64_SOURCE_MISMATCH');
  const source = before.toString('utf8');
  if (source.split(ANCHOR).length !== 2) fail('SDK_BASE64_ANCHOR_MISMATCH');
  const after = Buffer.from(source.replace(ANCHOR, REPLACEMENT));
  if (digest(after) !== PATCHED_SHA256) fail('SDK_BASE64_PATCH_MISMATCH');
  const temporary = file + '.noteai-' + randomUUID() + '.tmp';
  try {
    await fs.writeFile(temporary, after, { flag: 'wx', mode: info.mode & 0o777 });
    await regularFile(file);
    if (digest(await fs.readFile(file)) !== beforeSHA) fail('SDK_BASE64_SOURCE_CHANGED');
    await fs.rename(temporary, file);
  } finally {
    await fs.unlink(temporary).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  }
  if (digest(await fs.readFile(file)) !== PATCHED_SHA256) fail('SDK_BASE64_READBACK_MISMATCH');
  return { status: 'patched', sdk_version: VERSION, schema_version: VERSION,
    before_sha256: beforeSHA, after_sha256: PATCHED_SHA256, bytes: after.length };
}

try {
  if (process.argv.length !== 3) fail('SDK_BASE64_USAGE');
  process.stdout.write(JSON.stringify(await apply(process.argv[2])) + '\n');
} catch (error) {
  const code = typeof error?.code === 'string' && error.code.startsWith('SDK_BASE64_')
    ? error.code : 'SDK_BASE64_PATCH_FAILED';
  process.stderr.write(JSON.stringify({ code }) + '\n');
  process.exitCode = 1;
}
