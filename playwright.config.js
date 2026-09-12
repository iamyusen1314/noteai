const { defineConfig, devices } = require('@playwright/test');
const offline = process.env.NOTEAI_E2E_OFFLINE === '1';
const origin = offline ? 'http://127.0.0.1:5187' : 'http://127.0.0.1:5173';

module.exports = defineConfig({
  testDir: './tests/e2e',
  ...(offline ? { testMatch: [
    'chat-delivery-consistency.spec.js', 'sse-stall-guard.spec.js',
    'quota-ui.spec.js', 'admin-production-readonly.spec.js', 'frontend-local-assets.spec.js',
  ] } : {}),
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  reporter: [['list']],
  outputDir: 'test-results/e2e',
  use: {
    baseURL: origin,
    serviceWorkers: 'block',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `python3 -m http.server ${offline ? 5187 : 5173} --bind 127.0.0.1`,
    url: `${origin}/NoteAI_Pro_Demo_Framer.html`,
    reuseExistingServer: !offline,
    timeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
