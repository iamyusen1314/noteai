/* Menu-share metadata only; this never shares the current private page URL. */
// SDK source: https://res.wx.qq.com/open/js/jweixin-1.6.0.js (12938 bytes).
// SHA256: 0f17c4f7daf51a49a9627714ad2da6c037352442699ba8ceca68b7c6dc0b1dba
// The existing self-only image CSP also blocks the SDK's optional report image.
(function () {
  'use strict';
  const title = 'NoteAI Pro · 小红书创作者智能诊断平台';
  const description = '为小红书创作者提供内容诊断、创作与优化建议。';
  const link = 'https://noteaipro.com/';
  const imgUrl = 'https://noteaipro.com/assets/brand/noteai-share-logo.jpg';
  const jsApiList = ['updateAppMessageShareData', 'updateTimelineShareData'];
  let attempted = false;

  function signedConfig(value) {
    return value && value.enabled === true
      && typeof value.appId === 'string' && /^wx[a-zA-Z0-9]{16}$/.test(value.appId)
      && Number.isSafeInteger(value.timestamp) && value.timestamp > 0
      && typeof value.nonceStr === 'string' && /^[\x21-\x7e]{1,128}$/.test(value.nonceStr)
      && typeof value.signature === 'string' && /^[a-fA-F0-9]{40}$/.test(value.signature);
  }

  async function init(sdk = window.wx) {
    try {
      if (!/MicroMessenger/i.test(navigator.userAgent || '') || !sdk
          || !['config', 'ready', 'error', ...jsApiList].every(name => typeof sdk[name] === 'function')
          || typeof window.fetch !== 'function' || attempted) return false;
      attempted = true;
      // WeChat signs the complete current document URL, excluding its fragment.
      // That URL is sent only to our signer, never used as the shared link.
      const response = await window.fetch('/wechat/share-config', {
        method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({url: window.location.href.split('#')[0]}),
      });
      if (!response.ok) return false;
      const value = await response.json();
      if (!signedConfig(value)) return false;
      return await new Promise(resolve => {
        let settled = false;
        const finish = result => { if (!settled) { settled = true; resolve(result); } };
        sdk.error(() => finish(false));
        sdk.ready(() => {
          if (settled) return;
          try {
            sdk.updateAppMessageShareData({title, desc: description, link, imgUrl});
            sdk.updateTimelineShareData({title, link, imgUrl});
            // Registration is not evidence that a user actually shared a card.
            finish(true);
          } catch (_) { finish(false); }
        });
        sdk.config({debug: false, appId: value.appId, timestamp: value.timestamp,
          nonceStr: value.nonceStr, signature: value.signature, jsApiList: [...jsApiList]});
      });
    } catch (_) { return false; }
  }

  // Allows a reviewed self-hosted SDK to be supplied without loading any CDN.
  window.NoteAIWechatShare = Object.freeze({init});
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { void init(); }, {once: true});
  } else {
    void init();
  }
}());
