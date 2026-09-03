const { test, expect } = require('@playwright/test');

const SENSITIVE_SENTINELS = [
  'PROMPT_SENTINEL_PRIVATE',
  'BODY_SENTINEL_PRIVATE',
  'REASONING_SENTINEL_PRIVATE',
  'ERROR_SENTINEL_PRIVATE',
  'REQUEST_ID_SENTINEL_PRIVATE',
  'PAYMENT_REF_SENTINEL_PRIVATE',
];

function detailPayload(overrides = {}) {
  return {
    user: {
      id: 'synthetic-user-id',
      username: 'synthetic_user',
      email: 'synthetic@example.invalid',
      phone_masked: '138****0000',
      created_at: '2026-07-12T01:02:03+00:00',
      last_login: '2026-07-12T02:03:04+00:00',
    },
    subscription: { tier: 'pro', used_monthly_credits: 6 },
    credits: { balance: 12, total_purchased: 30, total_used: 18 },
    month_usage: [],
    recent_usage: [
      {
        operation: 'analyze',
        source: 'mixed',
        cost_rmb: 1.23456,
        credits_used: 6,
        tokens_in: 1200,
        tokens_out: 300,
        model_calls: 2,
        model_names: '<img id="usage-ledger-xss" src=x onerror="window.__ledgerXss=1">claude:model',
        cost_mode: 'actual',
        recorded_at: '2026-07-12T03:04:05+00:00',
        prompt: SENSITIVE_SENTINELS[0],
        body: SENSITIVE_SENTINELS[1],
        reasoning: SENSITIVE_SENTINELS[2],
        error: SENSITIVE_SENTINELS[3],
        request_id: SENSITIVE_SENTINELS[4],
      },
      {
        operation: 'constructor',
        source: 'toString',
        cost_rmb: 'not-a-number',
        credits_used: null,
        tokens_in: -50,
        tokens_out: 'invalid',
        model_calls: 'invalid',
        model_names: 'safe-unknown-model',
        cost_mode: '__proto__',
        recorded_at: 'invalid-time',
      },
    ],
    credit_txns: [
      {
        type: 'usage',
        amount: -2,
        balance_after: 10,
        description: '<img id="description-ledger-xss" src=x onerror="window.__ledgerXss=1">wallet debit',
        paid_rmb: 0,
        package_id: '',
        payment_ref: SENSITIVE_SENTINELS[5],
        recorded_at: '2026-07-12T03:04:06+00:00',
        prompt: SENSITIVE_SENTINELS[0],
        body: SENSITIVE_SENTINELS[1],
        reasoning: SENSITIVE_SENTINELS[2],
        error: SENSITIVE_SENTINELS[3],
        request_id: SENSITIVE_SENTINELS[4],
      },
      {
        type: 'constructor',
        amount: 'invalid',
        balance_after: null,
        description: 'unknown transaction',
        paid_rmb: 'invalid',
        package_id: '__proto__',
        payment_ref: SENSITIVE_SENTINELS[5],
        recorded_at: 'invalid-time',
      },
    ],
    notes_stat: {},
    ...overrides,
  };
}

async function openAdminDetail(page, payload) {
  const requests = [];
  await page.route('https://cdnjs.cloudflare.com/**', route => route.abort('blockedbyclient'));
  await page.route('**/admin/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ method: request.method(), path: url.pathname });
    if (url.pathname === '/admin/users/synthetic-user-id' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      });
      return;
    }
    await route.abort('blockedbyclient');
  });
  await page.addInitScript(() => {
    localStorage.clear();
    window.__ledgerXss = 0;
  });
  await page.goto('/model/admin.html');
  await page.evaluate(() => {
    _adminToken = 'route-mock-admin-token';
    return showUser('synthetic-user-id');
  });
  await expect(page.locator('#user-modal')).toHaveClass(/open/);
  return requests;
}

test('admin detail renders separate safe usage and wallet ledgers from a fixed allowlist', async ({ page }) => {
  const requests = await openAdminDetail(page, detailPayload());

  await expect(page.getByText('最近 20 条用量')).toBeVisible();
  await expect(page.getByText('最近 20 条钱包积分变动')).toBeVisible();
  await expect(page.getByText(/不是一一对应关系/)).toBeVisible();
  await expect(page.getByText(/不代表完整历史/)).toBeVisible();

  const usageLedger = page.locator('[data-testid="admin-usage-ledger"]');
  await expect(usageLedger).toContainText('AI深度诊断');
  await expect(usageLedger).toContainText('套餐+钱包');
  await expect(usageLedger).toContainText('实际成本（以覆盖审计为准）');
  await expect(usageLedger).toContainText('总计费 6.0 积分');
  await expect(usageLedger).toContainText('1.5K');
  await expect(usageLedger).toContainText('<img id="usage-ledger-xss"');
  await expect(usageLedger).toContainText('未知操作');
  await expect(usageLedger).toContainText('未知来源');
  await expect(usageLedger).toContainText('未知成本口径');

  const walletLedger = page.locator('[data-testid="admin-credit-ledger"]');
  await expect(walletLedger).toContainText('钱包消费');
  await expect(walletLedger).toContainText('-2.0');
  await expect(walletLedger).toContainText('余额 10.0');
  await expect(walletLedger).toContainText('<img id="description-ledger-xss"');
  await expect(walletLedger).toContainText('未知变动');
  await expect(walletLedger).toContainText('未知积分包');

  await expect(page.locator('#usage-ledger-xss, #operation-ledger-xss, #description-ledger-xss, #txn-ledger-xss')).toHaveCount(0);
  expect(await page.evaluate(() => window.__ledgerXss)).toBe(0);
  const bodyText = await page.locator('body').textContent();
  for (const sentinel of SENSITIVE_SENTINELS) expect(bodyText).not.toContain(sentinel);
  const detailText = await page.locator('#um-content').textContent();
  expect(detailText).not.toContain('native code');
  expect(detailText).not.toContain('[object Object]');
  expect(detailText).not.toContain('Object.prototype');
  expect(detailText).not.toContain('constructor');
  expect(detailText).not.toContain('toString');
  expect(detailText).not.toContain('__proto__');

  expect(requests).toEqual([{ method: 'GET', path: '/admin/users/synthetic-user-id' }]);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(requests.filter(request => /analyze|generate|chat|billing|credits\/topup/.test(request.path))).toEqual([]);
});

test('admin detail shows fixed empty states for both recent ledgers', async ({ page }) => {
  const requests = await openAdminDetail(page, detailPayload({ recent_usage: [], credit_txns: [] }));

  await expect(page.locator('[data-testid="admin-usage-ledger"]')).toContainText('暂无最近用量记录');
  await expect(page.locator('[data-testid="admin-credit-ledger"]')).toContainText('暂无钱包积分变动');
  expect(requests).toEqual([{ method: 'GET', path: '/admin/users/synthetic-user-id' }]);
});
