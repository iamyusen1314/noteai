'use strict';
// Separate NoteAI Trends stdin boundary; Item34 bridge and upstream assets unchanged.
const fs = require('fs');
const { signFull } = require('./js/core/sign.js');
const { buildRapPure } = require('./js/pc/rap.js');
try {
  const raw = fs.readFileSync(0, 'utf8');
  if (Buffer.byteLength(raw) > 65536) throw Error('input_limit');
  const p = JSON.parse(raw);
  const keys = new Set(['api','data','a1','cookie','b1','dslPair','tier','now','version',
    'loadts','seq','envConst','envFpTail','webBuild','signVersion','appId','platform','webSsk']);
  const post = ['/api/sns/web/v1/homefeed', '/api/sns/web/v2/search/notes'].includes(p.api);
  const recommend = typeof p.api === 'string' &&
    /^\/api\/sns\/web\/v1\/search\/recommend\?keyword=[A-Za-z0-9%+_.~-]+$/.test(p.api);
  if (Object.keys(p).some(k => !keys.has(k)) || p.appId !== 'xhs-pc-web' ||
      !['0101','0301'].includes(p.tier) || (!post && !recommend) ||
      (post && (!p.data || typeof p.data !== 'object' || Array.isArray(p.data))) ||
      (recommend && p.data !== '')) throw Error('operation_not_allowed');
  const signed = signFull(p);
  const expectedLength = p.tier === '0301' ? 200 : 205;
  if (signed.x3.length !== expectedLength || !signed.x3.startsWith('mns' + p.tier + '_'))
    throw Error('signer_contract');
  const result = { xs: signed.xs, xt: signed.xt, xs_common: signed.xs_common };
  if (post) {
    const template = JSON.parse(fs.readFileSync(__dirname + '/js/pc/rap_fingerprint_template.json', 'utf8'));
    result.x_rap_param = buildRapPure({api:p.api, data:JSON.stringify(p.data),
      fingerprint:Buffer.from(template.bodyUnmaskedHex, 'hex')});
  }
  process.stdout.write(JSON.stringify(result));
} catch (_) {
  process.stderr.write('signer_failed');
  process.exitCode = 1;
}
