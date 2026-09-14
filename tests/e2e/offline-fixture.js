const { test: base, expect } = require('@playwright/test');

// These suites exercise synthetic responses only. Every unmocked request is
// blocked before transport except this finite list on the owned static server.
// A page-specific route remains able to fulfill its synthetic API response.
const staticPaths = new Set([
  '/NoteAI_Pro_Demo_Framer.html',
  '/model/admin.html',
  '/assets/vendor/echarts-5.4.3.min.js',
  '/assets/vendor/lucide-1.27.0.min.js',
  '/assets/vendor/qrcode-generator-2.0.4.js',
  '/assets/payment-native.js',
  '/assets/landing/v04-quality-engine.png',
]);

const test = base.extend({
  offlineNetwork: [async ({ context, baseURL }, use) => {
    const origin = new URL(baseURL).origin;
    if (!['http://127.0.0.1:5173', 'http://127.0.0.1:5187'].includes(origin)) {
      throw new Error('Offline UI suites require a loopback static origin');
    }
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === origin && url.pathname === '/runtime-config.js') {
        return route.fulfill({ contentType: 'application/javascript',
          body: `window.NOTEAI_API_BASE=${JSON.stringify(origin + '/synthetic-api')};` });
      }
      if (request.method() === 'GET' && url.origin === origin
          && staticPaths.has(url.pathname) && !url.search) {
        return route.continue();
      }
      return route.abort('blockedbyclient');
    });
    // No service-worker or WebSocket escape from the HTTP interception above.
    await context.routeWebSocket('**/*', socket => socket.close());
    await use();
  }, { auto: true }],
});

module.exports = { test, expect };
