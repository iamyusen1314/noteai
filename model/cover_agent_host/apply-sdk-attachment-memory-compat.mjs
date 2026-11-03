#!/usr/bin/env node
/** Build-only compatibility patch for the pinned OpenCode 2.1.2 initial attachments.
 * Never edits an unknown dependency or evaluates an image/model request.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

const VERSION = '2.1.2';
const ORIGINAL_SHA256 = '9c74c7aa0923e21ec0df7ee48c2574f75252acc7488c9af2dc8333e1615d64cb';
const PATCHED_SHA256 = 'bfbd1ac398c1cc6be27c22535daae0b05eb90005ab825b052a003110be74f8f3';
const ANCHOR = 'const files = input.files ? yield* Effect.forEach(input.files, materializeAttachment, { concurrency: 8 }) : undefined;';
const REPLACEMENT = ANCHOR.replace('concurrency: 8', 'concurrency: 1');
const digest = (body) => createHash('sha256').update(body).digest('hex');
const fail = (code) => { throw Object.assign(new Error(code), { code }); };

async function regularFile(file) {
  const info = await fs.lstat(file);
  if (!info.isFile() || info.isSymbolicLink()) fail('SDK_ATTACHMENT_REGULAR_FILE_REQUIRED');
  return info;
}

async function apply(modules) {
  if (!modules || !path.isAbsolute(modules)) fail('SDK_ATTACHMENT_ABSOLUTE_MODULES_REQUIRED');
  for (const name of ['sdk', 'core']) {
    const file = path.join(modules, '@opencode', name, 'package.json');
    await regularFile(file);
    const value = JSON.parse(await fs.readFile(file, 'utf8'));
    if (value.version !== VERSION) fail('SDK_ATTACHMENT_VERSION_MISMATCH');
  }
  const file = path.join(modules, '@opencode/core/dist/chunks/repository-cache-3xcrjpsd.js');
  const info = await regularFile(file);
  const before = await fs.readFile(file);
  const beforeSHA = digest(before);
  if (beforeSHA === PATCHED_SHA256) return { status: 'already_patched',
    sdk_version: VERSION, core_version: VERSION, before_sha256: beforeSHA,
    after_sha256: beforeSHA, bytes: before.length };
  if (beforeSHA !== ORIGINAL_SHA256) fail('SDK_ATTACHMENT_SOURCE_MISMATCH');
  const source = before.toString('utf8');
  if (source.split(ANCHOR).length !== 2) fail('SDK_ATTACHMENT_ANCHOR_MISMATCH');
  const after = Buffer.from(source.replace(ANCHOR, REPLACEMENT));
  if (digest(after) !== PATCHED_SHA256) fail('SDK_ATTACHMENT_PATCH_MISMATCH');
  const temporary = file + '.noteai-' + randomUUID() + '.tmp';
  try {
    await fs.writeFile(temporary, after, { flag: 'wx', mode: info.mode & 0o777 });
    await regularFile(file);
    if (digest(await fs.readFile(file)) !== beforeSHA) fail('SDK_ATTACHMENT_SOURCE_CHANGED');
    await fs.rename(temporary, file);
  } finally {
    await fs.unlink(temporary).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  }
  if (digest(await fs.readFile(file)) !== PATCHED_SHA256) fail('SDK_ATTACHMENT_READBACK_MISMATCH');
  return { status: 'patched', sdk_version: VERSION, core_version: VERSION,
    before_sha256: beforeSHA, after_sha256: PATCHED_SHA256, bytes: after.length };
}

try {
  if (process.argv.length !== 3) fail('SDK_ATTACHMENT_USAGE');
  process.stdout.write(JSON.stringify(await apply(process.argv[2])) + '\n');
} catch (error) {
  const code = typeof error?.code === 'string' && error.code.startsWith('SDK_ATTACHMENT_')
    ? error.code : 'SDK_ATTACHMENT_PATCH_FAILED';
  process.stderr.write(JSON.stringify({ code }) + '\n');
  process.exitCode = 1;
}
