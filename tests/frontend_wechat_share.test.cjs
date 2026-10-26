const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../assets/wechat-share.js'), 'utf8');
// Exact reviewed public source: https://res.wx.qq.com/open/js/jweixin-1.6.0.js
const vendor = fs.readFileSync(path.join(__dirname, '../assets/vendor/jweixin-1.6.0.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../NoteAI_Pro_Demo_Framer.html'), 'utf8');
const signed = {enabled: true, appId: 'wx0123456789abcdef', timestamp: 1793000000,
  nonceStr: 'synthetic-nonce', signature: 'a'.repeat(40)};

function fixture({ua = 'iPhone MicroMessenger', response = signed, sdkPresent = true, failRequest = false} = {}) {
  const calls = [], shares = [], configs = [];
  let ready, error, loaded;
  const sdk = {
    ready: callback => { ready = callback; }, error: callback => { error = callback; },
    config: value => { configs.push(value); },
    updateAppMessageShareData: value => shares.push(['friend', value]),
    updateTimelineShareData: value => shares.push(['timeline', value]),
  };
  const window = {location: {href: 'https://noteaipro.com/?page=report&report_id=private-report#private-session'},
    fetch: async (url, options) => {
      calls.push({url, options});
      if (failRequest) throw new Error('synthetic unavailable');
      return {ok: response !== null, json: async () => response};
    }};
  if (sdkPresent) window.wx = sdk;
  Object.defineProperty(window, 'localStorage', {get() { throw new Error('must not read product session'); }});
  const context = vm.createContext({window, navigator: {userAgent: ua},
    document: {readyState: 'loading', addEventListener: (name, callback) => {
      assert.equal(name, 'DOMContentLoaded'); loaded = callback;
    }}});
  vm.runInContext(source, context);
  return {window, sdk, calls, shares, configs, ready: () => ready(), error: () => error(),
    loaded: () => loaded()};
}

test('ordinary browsers and missing SDK do not request a signature', {timeout: 1000}, async () => {
  for (const options of [{ua: 'Desktop Browser'}, {ua: 'iPhone Mobile'}, {sdkPresent: false}]) {
    const f = fixture(options);
    assert.equal(await f.window.NoteAIWechatShare.init(), false);
    assert.equal(f.calls.length, 0);
    assert.equal(f.configs.length, 0);
  }
});

test('anonymous signing keeps the exact URL without hash; both shared links stay public', {timeout: 1000}, async () => {
  const f = fixture();
  const pending = f.window.NoteAIWechatShare.init();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls.length, 1);
  const {url, options} = f.calls[0];
  assert.equal(url, '/wechat/share-config');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'omit');
  assert.equal(options.redirect, 'error');
  assert.equal(options.cache, 'no-store');
  assert.equal(options.referrerPolicy, 'no-referrer');
  assert.deepEqual(JSON.parse(options.body), {url: 'https://noteaipro.com/?page=report&report_id=private-report'});
  assert.deepEqual(Object.keys(options.headers).sort(), ['Accept', 'Content-Type']);
  assert.equal(f.configs.length, 1);
  assert.equal(f.configs[0].debug, false);
  assert.deepEqual(Array.from(f.configs[0].jsApiList), ['updateAppMessageShareData', 'updateTimelineShareData']);
  assert.equal(f.shares.length, 0);
  f.ready();
  assert.equal(await pending, true);
  assert.deepEqual(f.shares.map(([kind]) => kind), ['friend', 'timeline']);
  for (const [, value] of f.shares) {
    assert.equal(value.link, 'https://noteaipro.com/');
    assert.equal(value.imgUrl, 'https://noteaipro.com/assets/brand/noteai-share-logo.jpg');
    assert.equal(value.title, 'NoteAI Pro · 小红书创作者智能诊断平台');
    assert.doesNotMatch(JSON.stringify(value), /private-report|private-session|report_id/);
  }
  assert.equal(await f.window.NoteAIWechatShare.init(), false);
  f.loaded();
  assert.equal(f.calls.length, 1);
});

test('a reviewed SDK can be injected after an initial missing-SDK skip', {timeout: 1000}, async () => {
  const f = fixture({sdkPresent: false});
  assert.equal(await f.window.NoteAIWechatShare.init(), false);
  const pending = f.window.NoteAIWechatShare.init(f.sdk);
  await new Promise(resolve => setImmediate(resolve));
  f.ready();
  assert.equal(await pending, true);
  assert.equal(f.calls.length, 1);
});

test('disabled, unavailable and malformed signatures fail silently without retries', {timeout: 1000}, async () => {
  for (const options of [{response: {enabled: false}}, {response: null}, {failRequest: true},
    {response: {...signed, signature: 'invalid'}}, {response: {...signed, appId: ''}},
    {response: {...signed, timestamp: '1793000000'}}, {response: {...signed, nonceStr: '\n'}}]) {
    const f = fixture(options);
    assert.equal(await f.window.NoteAIWechatShare.init(), false);
    assert.equal(f.configs.length, 0);
    assert.equal(f.shares.length, 0);
    assert.equal(await f.window.NoteAIWechatShare.init(), false);
    assert.equal(f.calls.length, 1);
  }
});

test('SDK errors and exceptions cannot publish metadata or disturb the product', {timeout: 1000}, async () => {
  const f = fixture();
  const pending = f.window.NoteAIWechatShare.init();
  await new Promise(resolve => setImmediate(resolve));
  f.error(); f.ready();
  assert.equal(await pending, false);
  assert.equal(f.shares.length, 0);
  const throwing = fixture();
  throwing.sdk.config = () => { throw new Error('synthetic SDK failure'); };
  assert.equal(await throwing.window.NoteAIWechatShare.init(), false);
  assert.equal(throwing.shares.length, 0);
});

test('HTML uses public metadata and exact original JPG, with ordered self-hosted deferred scripts', {timeout: 1000}, () => {
  assert.match(html, /<meta property="og:title" content="NoteAI Pro · 小红书创作者智能诊断平台">/);
  assert.match(html, /<meta property="og:description" content="为小红书创作者提供内容诊断、创作与优化建议。">/);
  assert.match(html, /<meta property="og:url" content="https:\/\/noteaipro\.com\/">/);
  assert.match(html, /<meta property="og:image" content="https:\/\/noteaipro\.com\/assets\/brand\/noteai-share-logo\.jpg">/);
  assert.match(html, /<link rel="canonical" href="https:\/\/noteaipro\.com\/">/);
  assert.match(html, /<link rel="icon" type="image\/jpeg" href="\/assets\/brand\/noteai-share-logo\.jpg">/);
  assert.match(html, /<script src="\/assets\/wechat-share\.js" defer><\/script>/);
  assert(html.indexOf('src="/assets/vendor/jweixin-1.6.0.js" defer')
    < html.indexOf('src="/assets/wechat-share.js" defer'));
  const logo = fs.readFileSync(path.join(__dirname, '../assets/brand/noteai-share-logo.jpg'));
  assert.equal(crypto.createHash('sha256').update(logo).digest('hex'),
    '515e2453bf01f2d6edf56ec98c758d40c46d1fd28e3e27d65412d8df25c95993');
});

test('not-ready SDK remains isolated without retries or sharing', {timeout: 1000}, async () => {
  const f = fixture();
  let settled = false;
  const pending = f.window.NoteAIWechatShare.init().then(value => { settled = true; return value; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false);
  assert.equal(f.calls.length, 1);
  assert.equal(f.shares.length, 0);
  f.error();
  assert.equal(await pending, false);
});

test('reviewed SDK uses actual config and share APIs with a synthetic Bridge only', {timeout: 1000}, async () => {
  assert.equal(Buffer.byteLength(vendor), 12938);
  assert.equal(crypto.createHash('sha256').update(vendor).digest('hex'),
    '0f17c4f7daf51a49a9627714ad2da6c037352442699ba8ceca68b7c6dc0b1dba');
  const bridge = [], reports = [], requests = [];
  const globals = {
    navigator: {userAgent: 'iPhone MicroMessenger/8.0.1', platform: 'iPhone'},
    location: {href: 'https://noteaipro.com/?page=report&report_id=synthetic-private#session'},
    document: {title: 'NoteAI Pro', readyState: 'complete', addEventListener() {}},
    // No real image or network: record the SDK's ancillary reporting attempt.
    Image: class {set src(value) {reports.push(value);}},
    WeixinJSBridge: {invoke(name, args, callback) {
      bridge.push({name, args});
      callback({errMsg: name + ':ok', subtype: 'wifi'});
    }, on() {}},
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => signed};
    },
  };
  globals.window = globals;
  const context = vm.createContext(globals);
  vm.runInContext(vendor, context);
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 1);
  const verification = bridge.find(x => x.name === 'preVerifyJSAPI');
  assert(verification);
  assert.equal(verification.args.verifyAppId, signed.appId);
  assert.equal(verification.args.verifySignature, signed.signature);
  assert.deepEqual(Array.from(verification.args.verifyJsApiList), ['updateAppMessageShareData', 'updateTimelineShareData']);
  const sharing = bridge.filter(x => ['updateAppMessageShareData', 'updateTimelineShareData'].includes(x.name));
  assert.equal(sharing.length, 2);
  for (const {args} of sharing) {
    assert.equal(args.link, 'https://noteaipro.com/');
    assert.equal(args.imgUrl, 'https://noteaipro.com/assets/brand/noteai-share-logo.jpg');
    assert.doesNotMatch(JSON.stringify(args), /synthetic-private|report_id|#session/);
  }
  assert.equal(reports.length, 1);
  assert.equal(new URL(reports[0]).origin, 'https://open.weixin.qq.com');
  assert.equal(new URL(reports[0]).pathname, '/sdk/report');
  // This synthetic Image is not a browser CSP test; production keeps img-src self.
});
