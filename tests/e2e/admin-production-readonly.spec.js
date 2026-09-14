const { test, expect } = require('./offline-fixture');


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

test('usage details distinguish unknown costs and loaded Prompt snapshots from actual model records', async ({ page }) => {
  await page.goto('/model/admin.html');
  const content = await page.evaluate(() => renderAdminCallDetails({status:'available', calls:[
    {binding:'physical_call', state:'unknown', requested_model:'doubao-seed-2-0-lite-260428',
      modality:'video_audio', model:null, known_cost_rmb:null, loaded_prompt_versions:[]},
    {binding:'historical_model_record_only', state:'not_recorded',model:'<img src=x onerror=alert(1)>',
      known_cost_rmb:0.1,loaded_prompt_versions:[{key:'creator.travel',source:'code_fallback',version:null,sha256:'a'.repeat(64)}]},
    {binding:'physical_call',state:'responded',model:'unpriced-model',known_cost_rmb:0,
      pricing_status:'unpriced',usage_status:'incomplete',loaded_prompt_versions:[]},
    {binding:'physical_call',state:'responded',model:'missing-usage-model',known_cost_rmb:0,
      pricing_status:'usage_missing',usage_status:'usage_missing',input_tokens:0,output_tokens:0,
      cache_read_input_tokens:0,cache_write_input_tokens:0,audio_input_tokens:0,
      audio_cache_read_input_tokens:0,unclassified_input_tokens:0,loaded_prompt_versions:[]},
  ]}));
  await page.locator('body').evaluate((el, html) => { el.innerHTML = html; }, content);
  await expect(page.locator('body')).toContainText('已知模型成本 待核实');
  await expect(page.locator('body')).toContainText('本次模板归属与历史累计快照分别标注');
  await expect(page.locator('body')).toContainText('步骤 历史未记录');
  await expect(page.locator('body')).toContainText('历史模型账目：未关联物理调用');
  await expect(page.locator('body img')).toHaveCount(0);
  expect(content).not.toContain('¥0.000000');
  expect(content).not.toContain('输入 0');
  expect(content).not.toContain('输出 0');
});


test('new call trace shows exact step and instruction role without upgrading historical snapshots', async ({ page }) => {
  await page.goto('/model/admin.html');
  const content = await page.evaluate(() => renderAdminCallDetails({status:'available',calls:[
    {model:'doubao-seed-2-0-lite-260428', task:'media_understanding',step:'video_audio_understanding',
      prompt_scope:'call_templates',instruction_role:'user',instruction_sha256:'b'.repeat(64),loaded_prompt_versions:[]},
    {model:'claude-haiku-4-5-20251001',task:'diagnosis',step:'diagnosis_content',prompt_domain:'旅行',
      prompt_scope:'call_templates',instruction_role:'system',instruction_sha256:'a'.repeat(64),
      loaded_prompt_versions:[{key:'agent_content_system',source:'managed_prompts',version:8,sha256:'c'.repeat(64)}]},
  ]}));
  await page.locator('body').evaluate((el, html) => { el.innerHTML=html; }, content);
  await expect(page.locator('body')).toContainText('步骤 视频与原音轨理解');
  await expect(page.locator('body')).toContainText('步骤 诊断：内容专家');
  await page.getByText('本次使用的 Prompt 模板（0项）',{exact:true}).click();
  await expect(page.locator('body')).toContainText('本步骤使用代码内置指令');
  await expect(page.locator('body')).toContainText('素材指令 SHA256：'+'b'.repeat(64));
  await page.getByText('本次使用的 Prompt 模板（1项）',{exact:true}).click();
  await expect(page.locator('body')).toContainText('agent_content_system');
  await expect(page.locator('body')).toContainText('行业 旅行');
});

test('user usage Prompt disclosure stays clickable inside the scrolling detail modal', async ({ page }) => {
  await page.goto('/model/admin.html');
  await page.evaluate(() => {
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('um-content').innerHTML = '<div style="overflow-x:auto"><table style="min-width:820px"><tbody>' + renderAdminUsageLedger([
      {operation:'analyze',source:'credit',model_names:'claude:claude-haiku-4-5-20251001,doubao:doubao-seed-2-0-lite-260428',
        call_details:{status:'available',calls:[{model:'claude-haiku-4-5-20251001',
          loaded_prompt_versions:[{key:'creator.travel',source:'code_fallback',version:null,sha256:'a'.repeat(64)}]}]}},
    ]) + '</tbody></table></div>';
    openModal('user-modal');
  });
  for (const width of [1280, 390]) {
    await page.setViewportSize({width,height:900});
    const outer = page.getByText('查看本次调用、Prompt 版本与成本依据',{exact:true});
    if (width === 1280) await outer.click();
    const inner = page.getByText('历史累计 Prompt 快照（1项）',{exact:true});
    await inner.click();
    await expect(page.locator('#um-content')).toContainText('creator.travel');
    const box = await inner.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await inner.click();
  }
});

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

test('published original Admin supports login, user quota detail and confirmed logout under strict CSP', async ({page, context, baseURL}) => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const cp = require('node:child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'noteai-admin-csp-'));
  fs.mkdirSync(path.join(dir,'assets'), {recursive:true});
  fs.copyFileSync('model/admin.html', path.join(dir,'index.html'));
  cp.execFileSync('python3',['tools/build_public_product_frontend.py',dir]);
  const errors=[]; let loggedIn=false; let logoutOk=true; let meMode='ok';
  page.on('pageerror', error => errors.push(error.message));
  const json = (route,value,status=200) => route.fulfill({status,json:value});
  await context.route('**/*', async route => {
    const url=new URL(route.request().url());
    if(url.origin!==baseURL) return route.abort();
    if(url.pathname==='/admin-published') return route.fulfill({path:path.join(dir,'index.html'),contentType:'text/html',headers:{'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"}});
    if(['/assets/product-app.js','/assets/product-events.js'].includes(url.pathname)) return route.fulfill({path:path.join(dir,url.pathname),contentType:'application/javascript'});
    if(url.pathname==='/assets/vendor/echarts-5.4.3.min.js') return route.fulfill({path:path.resolve('.'+url.pathname),contentType:'application/javascript'});
    if(url.pathname==='/admin/login') { loggedIn=true; return json(route,{token:'admin_synthetic_only',username:'synthetic-admin'}); }
    if(url.pathname==='/admin/logout') { if(logoutOk) loggedIn=false; return json(route,logoutOk?{ok:true}:{detail:'unavailable'},logoutOk?200:503); }
    if(!loggedIn) return json(route,{detail:'forbidden'},403);
    if(url.pathname==='/admin/me') {
      if(meMode==='network') return route.abort();
      if(meMode==='malformed') return route.fulfill({status:200,body:'invalid-json'});
      if(meMode==='503') return json(route,{detail:'temporarily unavailable'},503);
      if(meMode==='403') return json(route,{detail:'expired'},403);
      return json(route,{username:'synthetic-admin'});
    }
    if(url.pathname==='/admin/capabilities') return json(route,{mode:'production_read_only',capabilities:{}});
    if(url.pathname==='/admin/overview') return json(route,overview);
    if(url.pathname==='/admin/ai-operations') return json(route,{operations:{},settlements:{},outbox:{}});
    if(url.pathname==='/admin/users') return json(route,{total:1,users:[{id:'synthetic-user',username:'synthetic_user',phone_masked:'138****0000',tier:'free',month_ops:1,month_cost:0.3}]});
    if(url.pathname==='/admin/users/synthetic-user') return json(route,{user:{id:'synthetic-user',username:'synthetic_user',phone_masked:'138****0000'},subscription:{tier:'free',used_monthly_credits:6},credits:{balance:0},quota:{monthly_limit:12,monthly_remaining:6},month_usage:[],recent_usage:[],credit_txns:[]});
    return json(route,{detail:'offline fixture'},503);
  });
  await page.goto('/admin-published');
  await page.locator('#login-username').fill('synthetic-admin');
  await page.locator('#login-password').fill('synthetic-only');
  await page.getByRole('button',{name:'登录管理后台',exact:true}).click();
  await expect(page.locator('#app')).toBeVisible();
  await expect(page.locator('#login-password')).toHaveValue('');
  const sessionKey = await page.evaluate(() => Object.keys(sessionStorage).find(key=>sessionStorage.getItem(key)==='admin_synthetic_only'));
  expect(sessionKey).toBeTruthy();
  for (const mode of ['503', 'network', 'malformed']) {
    meMode=mode;
    await page.reload();
    await expect(page.locator('#app')).toBeHidden();
    await expect(page.locator('#login-error')).toContainText('会话已保留');
    expect(await page.evaluate(key=>sessionStorage.getItem(key),sessionKey)).toBe('admin_synthetic_only');
    meMode='ok';
    await page.reload();
    await expect(page.locator('#app')).toBeVisible();
  }
  meMode='403';
  await page.reload();
  await expect(page.locator('#app')).toBeHidden();
  expect(await page.evaluate(key=>sessionStorage.getItem(key),sessionKey)).toBeNull();
  meMode='ok';
  await page.locator('#login-password').fill('synthetic-only');
  await page.getByRole('button',{name:'登录管理后台',exact:true}).click();
  await expect(page.locator('#app')).toBeVisible();
  await page.locator('.nav-item').filter({hasText:'用户管理'}).click();
  await page.getByRole('button',{name:'详情',exact:true}).click();
  await expect(page.locator('#um-content')).toContainText('套餐周期额度: 12.0；剩余: 6.0');
  await expect(page.locator('#um-content')).toContainText('钱包积分余额: 0.0');
  await page.locator('#user-modal .modal-close').click();
  await page.getByRole('button',{name:'退出登录',exact:true}).click();
  await expect(page.locator('#login-screen')).toBeVisible();
  expect(loggedIn).toBe(false);
  await expect(page.locator('#login-error')).toBeHidden();
  await page.locator('#login-password').fill('synthetic-only');
  await page.getByRole('button',{name:'登录管理后台',exact:true}).click();
  await expect(page.locator('#app')).toBeVisible();
  logoutOk=false;
  await page.getByRole('button',{name:'退出登录',exact:true}).click();
  await expect(page.locator('#login-error')).toContainText('服务端会话撤销未确认');
  expect(errors).toEqual([]);
  fs.rmSync(dir,{recursive:true,force:true});
});
