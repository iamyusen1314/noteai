'use strict';
// NoteAI stdin boundary. Upstream CLI/Creator/remote-script entrypoints are unused.
const fs = require('fs');
const { generateB1 } = require('./js/core/b1.js');
const { signFull } = require('./js/core/sign.js');
const { buildRapPure } = require('./js/pc/rap.js');
try {
  const raw = fs.readFileSync(0, 'utf8');
  if (Buffer.byteLength(raw) > 65536) throw Error('input_limit');
  const input = JSON.parse(raw);
  let result;
  if (input.operation === 'b1') {
    result = { b1: generateB1(input.options).b1 };
  } else if (input.operation === 'sign') {
    const p = input.payload;
    const keys = new Set(['api','data','a1','cookie','b1','dslPair','tier','now','version',
      'loadts','seq','envConst','envFpTail','webBuild','signVersion','appId','platform']);
    if (Object.keys(p).some(k => !keys.has(k)) || p.appId !== 'xhs-pc-web' ||
        !['0101','0301'].includes(p.tier) || ![
          '/api/sns/web/v2/user/me', '/api/sns/web/v1/feed'
        ].includes(p.api)) throw Error('operation_not_allowed');
    const signed = signFull(p);
    const expectedLength = p.tier === '0301' ? 200 : 205;
    if (signed.x3.length !== expectedLength || !signed.x3.startsWith('mns' + p.tier + '_'))
      throw Error('signer_contract');
    result = { xs: signed.xs, xt: signed.xt, xs_common: signed.xs_common };
    if (p.api === '/api/sns/web/v1/feed') {
      const template = JSON.parse(fs.readFileSync(__dirname + '/js/pc/rap_fingerprint_template.json', 'utf8'));
      result.x_rap_param = buildRapPure({api:p.api, data:JSON.stringify(p.data),
        fingerprint:Buffer.from(template.bodyUnmaskedHex, 'hex')});
    }
  } else throw Error('operation_not_allowed');
  process.stdout.write(JSON.stringify(result));
} catch (_) {
  process.stderr.write('signer_failed');
  process.exitCode = 1;
}
