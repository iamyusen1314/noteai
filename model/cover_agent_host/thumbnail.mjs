/** Deterministic pixel preview using the Skill's existing browser dependency. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export async function makeThumbnail({ pngPath, outputRoot, skillDir }) {
  const original = await fs.readFile(pngPath);
  const hash = createHash('sha256').update(original).digest('hex');
  await fs.mkdir(outputRoot, { recursive: true });
  const output = path.join(outputRoot, hash + '-240x320.png');
  const { launch } = await import(pathToFileURL(path.join(skillDir, 'scripts/_browser.mjs')).href);
  const browser = await launch();
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 240, height: 320, deviceScaleFactor: 1 });
    await page.setJavaScriptEnabled(false);
    await page.setRequestInterception(true);
    page.on('request', (request) => { if (request.url().startsWith('data:image/png;base64,')) request.continue(); else request.abort(); });
    await page.setContent(`<html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'none'; connect-src 'none'"><style>html,body{margin:0;width:240px;height:320px;overflow:hidden}img{display:block;width:240px;height:320px;object-fit:contain}</style></head><body><img src="data:image/png;base64,${original.toString('base64')}"></body></html>`, { waitUntil: 'load' });
    const loaded = await page.evaluate(() => document.images[0]?.complete && document.images[0].naturalWidth > 0);
    if (!loaded) throw new Error('THUMBNAIL_IMAGE_NOT_LOADED');
    await page.screenshot({ path: output, type: 'png' });
  } finally { await browser.close(); }
  const bytes = await fs.readFile(output);
  if (bytes.readUInt32BE(16) !== 240 || bytes.readUInt32BE(20) !== 320) throw new Error('THUMBNAIL_DIMENSION_MISMATCH');
  return { path: output, sha256: createHash('sha256').update(bytes).digest('hex'), width: 240, height: 320, source_sha256: hash, model_calls: 0 };
}
