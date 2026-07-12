const { test, expect } = require('@playwright/test');

const SENSITIVE_SENTINELS = [
  'PROMPT_SENTINEL_PRIVATE',
  'BODY_SENTINEL_PRIVATE',
  'REASONING_SENTINEL_PRIVATE',
];

function overviewPayload(coverage) {
  return {
    users: {
      total: 9,
      today_new: 1,
      active_7d: 6,
      active_month: 6,
      tier_distribution: { free: 7, pro_plus: 2 },
    },
    finance: {
      total_revenue: 598,
      mrr: 598,
      api_cost: 4.703,
      actual_margin_ready: coverage?.actual_margin_ready,
      margin_pct: 99.2,
      total_tokens: 977900,
      coverage,
    },
    usage: { by_operation: [] },
    system: {
      model_exists: true,
      model_size_mb: 1.3,
      database_backend: 'postgresql',
      database_ok: true,
      server_time: '2026-07-12T11:43:00+00:00',
    },
  };
}

function revenuePayload(coverage) {
  return {
    sub_revenue_estimate: 598,
    daily_topup: [],
    daily_api_cost: [{ day: '2026-07-12', cost: 4.703, tokens: 977900 }],
    coverage,
  };
}

function usagePayload(coverage) {
  return {
    coverage,
    by_operation: [],
    top_users: [],
    daily_trend: [],
    by_source: [],
    by_model: [{
      model: '<img id="coverage-xss" src=x onerror="window.__coverageXss=1">claude-sonnet-4-6',
      input_tokens: 100,
      cache_read_tokens: 20,
      cache_write_tokens: 0,
      output_tokens: 30,
      known_cost_rmb: 1.25,
      prompt: SENSITIVE_SENTINELS[0],
      body: SENSITIVE_SENTINELS[1],
      reasoning: SENSITIVE_SENTINELS[2],
    }],
    cache: { read_tokens: 20, write_tokens: 0 },
  };
}

async function openCoveragePages(page, coverage) {
  const requests = [];
  await page.route('https://cdnjs.cloudflare.com/**', route => route.abort('blockedbyclient'));
  await page.route('**/admin/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path: pathname });
    const payload = {
      '/admin/overview': overviewPayload(coverage),
      '/admin/revenue': revenuePayload(coverage),
      '/admin/usage-stats': usagePayload(coverage),
    }[pathname];
    if (request.method() === 'GET' && payload) {
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
    window.__coverageXss = 0;
    window.echarts = { init: () => ({ setOption: () => {} }) };
  });
  await page.goto('/model/admin.html');
  await page.evaluate(async () => {
    _adminToken = 'route-mock-admin-token';
    await loadDashboard();
    await loadRevenue();
    await loadUsage();
  });
  return requests;
}

test('incomplete coverage explains the monthly and recent-30-day operation-record cohorts', async ({ page }) => {
  const coverage = {
    total_records: 35,
    strict_actual_records: 4,
    legacy_unverifiable_records: 31,
    partial_records: 0,
    unpriced_records: 0,
    usage_incomplete_records: 0,
    strict_actual_pct: 11.4,
    actual_margin_ready: false,
    prompt: SENSITIVE_SENTINELS[0],
    body: SENSITIVE_SENTINELS[1],
    reasoning: SENSITIVE_SENTINELS[2],
  };
  const requests = await openCoveragePages(page, coverage);

  const dashboardCoverage = page.locator('#d-margin');
  await expect(dashboardCoverage).toContainText('本月成本覆盖不完整，毛利仅供参考');
  await expect(dashboardCoverage).toContainText('严格实际 4/35 条操作记录（11.4%）');
  await expect(dashboardCoverage).toContainText('历史不可复算 31 条操作记录');
  await expect(dashboardCoverage).not.toContainText('实际毛利 99.2%');

  await expect(page.locator('#r-sub-note')).toHaveText('按当前有效套餐人数 × 套餐价估算，不是支付流水。');
  await expect(page.locator('#r-margin')).toHaveText('覆盖不完整');
  const revenueCoverage = page.locator('#revenue-cost-audit');
  await expect(revenueCoverage).toContainText('最近30日成本覆盖不完整，不可宣称实际毛利');
  await expect(revenueCoverage).toContainText('严格实际 4/35 条操作记录（11.4%）');
  await expect(revenueCoverage).toContainText('历史不可复算 31 条操作记录');
  await expect(revenueCoverage).toContainText('部分计价 0 条操作记录');
  await expect(revenueCoverage).toContainText('未计价 0 条操作记录');
  await expect(revenueCoverage).toContainText('用量不完整 0 条操作记录');
  await expect(revenueCoverage).toContainText('严格实际 = 具备完整逐模型用量与价格证据的操作记录');
  await expect(revenueCoverage).toContainText('历史不可复算 = 逐模型成本审计上线前、缺少完整明细的操作记录，系统不会伪造回填');

  const usageCoverage = page.locator('#usage-cost-audit');
  await expect(usageCoverage).toContainText('最近30日成本覆盖不完整，不可宣称实际毛利');
  await expect(usageCoverage).toContainText('严格实际 4/35 条操作记录（11.4%）');
  await expect(usageCoverage).toContainText('历史不可复算 31 条操作记录');
  await expect(usageCoverage).toContainText('严格实际 = 具备完整逐模型用量与价格证据的操作记录');
  await expect(usageCoverage).toContainText('历史不可复算 = 逐模型成本审计上线前、缺少完整明细的操作记录，系统不会伪造回填');
  await expect(usageCoverage).toContainText('<img id="coverage-xss"');
  await expect(page.locator('#coverage-xss')).toHaveCount(0);
  expect(await page.evaluate(() => window.__coverageXss)).toBe(0);

  const bodyText = await page.locator('body').textContent();
  expect(bodyText).not.toContain('undefined');
  expect(bodyText).not.toContain('NaN');
  for (const sentinel of SENSITIVE_SENTINELS) expect(bodyText).not.toContain(sentinel);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
});

test('complete coverage is the only state that shows the actual margin percentage', async ({ page }) => {
  await openCoveragePages(page, {
    total_records: 35,
    strict_actual_records: 35,
    legacy_unverifiable_records: 0,
    partial_records: 0,
    unpriced_records: 0,
    usage_incomplete_records: 0,
    strict_actual_pct: 100,
    actual_margin_ready: true,
  });

  await expect(page.locator('#d-margin')).toContainText('实际毛利 99.2%');
  await expect(page.locator('#d-margin')).toContainText('本月严格实际 35/35 条操作记录（100.0%）');
  await expect(page.locator('#r-margin')).toHaveText('99%');
  await expect(page.locator('#revenue-cost-audit')).toContainText('最近30日成本覆盖完整，可按实际成本口径查看毛利');
  await expect(page.locator('#usage-cost-audit')).toContainText('最近30日成本覆盖完整，可使用实际毛利');
});

test('missing coverage uses fixed safe wording without undefined or NaN', async ({ page }) => {
  await openCoveragePages(page, undefined);

  await expect(page.locator('#d-margin')).toContainText('本月成本覆盖数据不可用，毛利仅供参考');
  await expect(page.locator('#revenue-cost-audit')).toContainText('最近30日成本覆盖数据不可用，不可宣称实际毛利');
  await expect(page.locator('#usage-cost-audit')).toContainText('最近30日成本覆盖数据不可用，不可宣称实际毛利');

  const bodyText = await page.locator('body').textContent();
  expect(bodyText).not.toContain('undefined');
  expect(bodyText).not.toContain('NaN');
});

test('empty coverage uses fixed safe wording without undefined or NaN', async ({ page }) => {
  await openCoveragePages(page, {
    total_records: 0,
    strict_actual_records: 0,
    legacy_unverifiable_records: 0,
    partial_records: 0,
    unpriced_records: 0,
    usage_incomplete_records: 0,
    actual_margin_ready: false,
  });

  await expect(page.locator('#d-margin')).toContainText('本月暂无用量记录，无法计算实际毛利');
  await expect(page.locator('#revenue-cost-audit')).toContainText('最近30日暂无用量记录，无法计算实际毛利');
  await expect(page.locator('#usage-cost-audit')).toContainText('最近30日暂无用量记录，无法计算实际毛利');
  const bodyText = await page.locator('body').textContent();
  expect(bodyText).not.toContain('undefined');
  expect(bodyText).not.toContain('NaN');
});

const INVALID_COVERAGE_CASES = [
  {
    name: 'strict count above total cannot become complete even when ready is true',
    coverage: {
      total_records: 35,
      strict_actual_records: 36,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    },
  },
  {
    name: 'boolean count is rejected instead of coercing to one',
    coverage: {
      total_records: true,
      strict_actual_records: 1,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    },
  },
  {
    name: 'string count is rejected instead of coercing to a number',
    coverage: {
      total_records: 35,
      strict_actual_records: '35',
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    },
  },
  {
    name: 'fractional count is rejected instead of rounding',
    coverage: {
      total_records: 35,
      strict_actual_records: 4,
      legacy_unverifiable_records: 30.5,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: false,
    },
  },
  {
    name: 'negative count is rejected instead of clamping to zero',
    coverage: {
      total_records: 35,
      strict_actual_records: 4,
      legacy_unverifiable_records: 31,
      partial_records: 0,
      unpriced_records: -1,
      usage_incomplete_records: 1,
      actual_margin_ready: false,
    },
  },
  {
    name: 'unsafe integer count is rejected instead of risking precision loss',
    coverage: {
      total_records: Number.MAX_SAFE_INTEGER + 1,
      strict_actual_records: Number.MAX_SAFE_INTEGER + 1,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    },
  },
  {
    name: 'classification gap is rejected instead of presenting partial evidence as complete',
    coverage: {
      total_records: 35,
      strict_actual_records: 4,
      legacy_unverifiable_records: 30,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: false,
    },
  },
  {
    name: 'classification overcount is rejected instead of trusting inconsistent evidence',
    coverage: {
      total_records: 35,
      strict_actual_records: 4,
      legacy_unverifiable_records: 32,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: false,
    },
  },
];

for (const invalidCase of INVALID_COVERAGE_CASES) {
  test(invalidCase.name, async ({ page }) => {
    await openCoveragePages(page, invalidCase.coverage);

    await expect(page.locator('#d-margin')).toContainText('本月成本覆盖数据不可用，毛利仅供参考');
    await expect(page.locator('#d-margin')).not.toContainText('实际毛利 99.2%');
    await expect(page.locator('#r-margin')).toHaveText('覆盖不完整');
    await expect(page.locator('#revenue-cost-audit')).toContainText('最近30日成本覆盖数据不可用，不可宣称实际毛利');
    await expect(page.locator('#usage-cost-audit')).toContainText('最近30日成本覆盖数据不可用，不可宣称实际毛利');
    const bodyText = await page.locator('body').textContent();
    expect(bodyText).not.toContain('undefined');
    expect(bodyText).not.toContain('NaN');
  });
}

test('non-finite counts are rejected before any readiness decision', async ({ page }) => {
  await page.goto('/model/admin.html');
  const states = await page.evaluate(() => [
    adminCostCoverage({
      total_records: Number.NaN,
      strict_actual_records: 0,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    }),
    adminCostCoverage({
      total_records: Number.POSITIVE_INFINITY,
      strict_actual_records: 0,
      legacy_unverifiable_records: 0,
      partial_records: 0,
      unpriced_records: 0,
      usage_incomplete_records: 0,
      actual_margin_ready: true,
    }),
  ]);

  expect(states).toEqual([
    expect.objectContaining({ state: 'unavailable', ready: false }),
    expect.objectContaining({ state: 'unavailable', ready: false }),
  ]);
});
