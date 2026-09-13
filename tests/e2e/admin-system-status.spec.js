const { test, expect } = require('./offline-fixture');

function overviewPayload(system = {}) {
  return {
    users: {
      total: 9,
      today_new: 0,
      active_7d: 2,
      active_month: 3,
      tier_distribution: { free: 7, pro_plus: 2 },
    },
    finance: {
      total_revenue: 598,
      cash_received: 598,
      cash_refunded: 0,
      unmatched_cash: 0,
      api_cost: 17.03,
      actual_margin_ready: false,
      margin_pct: 97.2,
      total_tokens: 977900,
    },
    usage: { by_operation: [] },
    system: {
      model_exists: true,
      model_size_mb: 1.3,
      server_time: '2026-07-12T11:43:00+00:00',
      ...system,
    },
  };
}

async function openDashboard(page, system) {
  const requests = [];
  await page.route('https://cdnjs.cloudflare.com/**', route => route.abort('blockedbyclient'));
  await page.route('**/admin/overview', async route => {
    requests.push({ method: route.request().method(), path: new URL(route.request().url()).pathname });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(overviewPayload(system)),
    });
  });
  await page.addInitScript(() => {
    localStorage.clear();
    window.echarts = { init: () => ({ setOption: () => {} }) };
  });
  await page.goto('/model/admin.html');
  await page.evaluate(async () => {
    _adminToken = 'route-mock-admin-token';
    await loadDashboard();
  });
  return requests;
}

test('admin dashboard renders healthy API provider and PostgreSQL status', async ({ page }) => {
  const requests = await openDashboard(page, {
    ai_runtime: {
      status: 'configured',
      source: 'api_readiness',
      claude_status: 'configured',
      kimi_status: 'configured',
    },
    kimi_configured: true,
    claude_configured: true,
    database_backend: 'postgresql',
    database_ok: true,
  });

  const status = page.locator('#system-status');
  await expect(status).toContainText('Kimi API');
  await expect(status).toContainText('Claude API');
  await expect(status).toContainText('API 服务已配置');
  await expect(status).toContainText('PostgreSQL 正常');
  expect(requests).toEqual([{ method: 'GET', path: '/admin/overview' }]);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(await page.locator('body').textContent()).not.toContain('undefined');
});

test('admin dashboard distinguishes an unconfigured provider', async ({ page }) => {
  await openDashboard(page, {
    ai_runtime: {
      status: 'not_configured',
      source: 'api_readiness',
      claude_status: 'configured',
      kimi_status: 'not_configured',
    },
    kimi_configured: false,
    claude_configured: true,
    database_backend: 'postgresql',
    database_ok: true,
  });

  const status = page.locator('#system-status');
  await expect(status).toContainText('API 服务未配置');
  await expect(status).toContainText('API 服务已配置');
  expect(await page.locator('body').textContent()).not.toContain('undefined');
});

test('admin dashboard shows unavailable when API readiness is unreachable', async ({ page }) => {
  await openDashboard(page, {
    ai_runtime: {
      status: 'unavailable',
      source: 'api_readiness',
      claude_status: 'unavailable',
      kimi_status: 'unavailable',
    },
    kimi_configured: false,
    claude_configured: false,
    database_backend: 'postgresql',
    database_ok: true,
  });

  const status = page.locator('#system-status');
  await expect(status).toContainText('状态查询暂不可用');
  await expect(status).not.toContainText('API 服务未配置');
  expect(await page.locator('body').textContent()).not.toContain('undefined');
});

test('admin dashboard treats missing status fields as unavailable without undefined', async ({ page }) => {
  await openDashboard(page, {});

  const status = page.locator('#system-status');
  await expect(status).toContainText('状态查询暂不可用');
  await expect(status).toContainText('数据库状态不可检测');
  expect(await page.locator('body').textContent()).not.toContain('undefined');
});

test('release admission and usage are not presented as provider health', async ({page}) => {
  await openDashboard(page, {ai_runtime: {
    source:'api_public_status', status:'observed', kimi_status:'admission_open', claude_status:'not_in_public_route', upstream_probed:false,
    recent_usage:[{provider:'kimi',model:'kimi-k2.6',last_recorded_at:'2026-09-12T12:00:00Z'}],
  }, database_backend:'postgresql',database_ok:true});
  const status=page.locator('#system-status');
  await expect(status).toContainText('公开文字入口可接收请求');
  await expect(status).toContainText('当前公开路由未使用');
  await expect(status).toContainText('/public/status');
  await expect(status).toContainText('最近用量入账');
  await expect(status).toContainText('未发起供应商连通测试');
  await expect(status).not.toContainText('API 服务已配置');
});

test('supplier groups retain unknown usage and original cached observation without probes', async ({page}) => {
  await openDashboard(page, {});
  await page.evaluate(() => {
    document.getElementById('supplier-view').innerHTML=renderSupplierView({suppliers:[
      {id:'kimi',name:'Kimi K2.6',group:'generation_models',role:'诊断',business:['诊断'],enabled:true,source:'api_public_product_availability'},
      {id:'claude',name:'Claude',group:'generation_models',role:'原仲裁分工',business:[],enabled:false,reason:'当前通道地区条件不覆盖',source:'api_public_product_availability'},
      {id:'amap',name:'高德地图',group:'data_tools',role:'门店事实',business:[],enabled:false,source:'api_public_product_availability'},
      {id:'meituan_travel',name:'美团酒旅',group:'data_tools',role:'酒旅',business:['旅行'],enabled:true,source:'api_public_product_availability',latest:{observed_at:'2026-09-13T01:00:00Z',persisted_at:'2026-09-13T02:00:00Z',status:'partial',cached:true,http_requests:0,cli_invocations:0,cost_cny:null}},
    ],recent_usage:null});
    document.querySelectorAll('.page').forEach(el=>{ if(el.contains(document.getElementById('supplier-view'))) el.style.display='block'; });
  });
  const text=await page.locator('#supplier-view').textContent();
  expect(text).toContain('生成模型'); expect(text).toContain('数据 / 工具服务');
  expect(text).toContain('用量未知'); expect(text).toContain('缓存（非新检索）');
  expect(text).toContain('2026-09-13T01:00:00Z'); expect(text).not.toContain('2026-09-13T02:00:00Z');
  expect(text).toContain('待供应商账单确认'); expect(text).not.toContain('undefined');
});

test('complete provider answer preserves prices and text while rendering safe source media', async ({page}) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(() => renderProviderAnswer({observed_at:'2026-09-13T01:00:00Z',provider_response:
    '广州甲酒店 ￥4XX起/晚\n<img src=x onerror="window.unsafeSource=true">\n![房间](https://example.invalid/room.jpg)\n最后一段完整保留'},document.body,'test-source-answer'));
  const card=page.locator('#test-source-answer');
  await expect(card).toContainText('￥4XX起/晚'); await expect(card).toContainText('最后一段完整保留');
  expect(await card.locator('img').count()).toBe(1);
  expect(await card.locator('img').getAttribute('referrerpolicy')).toBe('no-referrer');
  expect(await page.evaluate(()=>window.unsafeSource)).toBeUndefined();
  expect(await card.locator('a').getAttribute('rel')).toBe('noopener noreferrer');
});
