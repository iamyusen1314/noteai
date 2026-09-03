const { test, expect } = require('@playwright/test');


const overview = {
  users: {
    total: 0,
    today_new: 0,
    active_7d: 0,
    active_month: 0,
    tier_distribution: {},
  },
  finance: {
    total_revenue: 0,
    cash_received: 0,
    cash_refunded: 0,
    unmatched_cash: 0,
    api_cost: 0,
    margin_pct: 0,
    total_tokens: 0,
    coverage: {
      total_records: 0,
      strict_actual_records: 0,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
    },
  },
  usage: { by_operation: [] },
  system: {
    ai_runtime: {
      status: 'unavailable',
      source: 'protected_status_unavailable',
      kimi_status: 'unavailable',
      claude_status: 'unavailable',
    },
    model_exists: true,
    model_size_mb: 1,
    database_backend: 'postgresql',
    database_ok: true,
    server_time: '2026-07-26T00:00:00+00:00',
  },
};


test('production Admin advertises read-only mode and disables mutation controls', async ({ page }) => {
  const writes = [];
  await page.route('https://cdnjs.cloudflare.com/**', route => route.abort('blockedbyclient'));
  await page.route('**/admin/capabilities', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      mode: 'production_read_only',
      read_only: true,
      capabilities: {
        business_mutation: false,
        prompt_mutation: false,
        model_mutation: false,
        crawler_control: false,
        tracking_requeue: false,
      },
    }),
  }));
  await page.route('**/admin/overview', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(overview),
  }));
  await page.route('**/admin/ai-operations', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      operations: { queued: 2, running: 1 },
      settlements: { needs_manual: 0 },
      outbox: { pending: 1 },
      oldest_queued_at: '2026-07-26T00:00:00+00:00',
      raw_payload_included: false,
      provider_called: false,
    }),
  }));
  page.on('request', request => {
    if (
      new URL(request.url()).pathname.startsWith('/admin/')
      && request.method() !== 'GET'
    ) {
      writes.push(request.url());
    }
  });
  await page.addInitScript(() => {
    sessionStorage.clear();
    window.echarts = { init: () => ({ setOption: () => {} }) };
  });
  await page.goto('/model/admin.html');
  await page.evaluate(async () => {
    _adminToken = 'route-mock-admin-token';
    await showApp();
  });

  await expect(page.locator('#admin-mode-banner')).toContainText('生产只读控制台');
  await expect(page.locator('#ai-operations-summary')).toContainText('等待执行');
  await expect(page.locator('#ai-operations-summary')).toContainText('2');
  await expect(page.locator('[data-capability="prompt_mutation"]').first()).toBeDisabled();
  await expect(page.locator('[data-capability="model_mutation"]').first()).toBeDisabled();
  await expect(page.locator('[data-capability="crawler_control"]').first()).toBeDisabled();
  expect(writes).toEqual([]);
});
