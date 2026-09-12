const { test, expect } = require('@playwright/test');


test('user and Admin pages load pinned scripts without an external CDN', async ({ page }) => {
  const externalScripts = [];
  page.on('request', request => {
    if (
      request.resourceType() === 'script'
      && new URL(request.url()).origin !== 'http://127.0.0.1:5173'
    ) {
      externalScripts.push(request.url());
    }
  });

  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect.poll(() => page.evaluate(() => typeof echarts)).toBe('object');
  await expect.poll(() => page.evaluate(() => typeof lucide)).toBe('object');

  await page.goto('/model/admin.html');
  await expect.poll(() => page.evaluate(() => typeof echarts)).toBe('object');
  expect(externalScripts).toEqual([]);
});

test('original public product works under strict script CSP with OTP and dynamic actions', async ({ page, context, baseURL }) => {
  const fs = require('node:fs');
  const path = require('node:path');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== baseURL) return route.abort();
    if (url.pathname === '/dist/index.html') return route.fulfill({
      path:path.resolve('dist/index.html'),contentType:'text/html',headers:{
        'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'",
      },
    });
    if (url.pathname === '/dist/runtime-config.js') return route.fulfill({
      contentType:'application/javascript',body:`window.NOTEAI_API_BASE=${JSON.stringify(baseURL + '/synthetic-api')};window.NOTEAI_PUBLIC_PRODUCT=true;`,
    });
    if (['/assets/product-app.js','/assets/product-events.js'].includes(url.pathname)) {
      return route.fulfill({path:path.resolve('dist'+url.pathname),contentType:'application/javascript'});
    }
    if (/^\/assets\/(vendor|landing)\/[a-zA-Z0-9_.-]+$/.test(url.pathname)) {
      if (fs.existsSync(path.resolve('.'+url.pathname))) return route.continue();
    }
    if (url.pathname === '/synthetic-api/public/status') return route.fulfill({json:{registration_open:true,ai_open:true}});
    if (url.pathname === '/synthetic-api/auth/verification/request') {
      expect(route.request().postDataJSON()).toEqual({channel:'phone',destination:'13800138000',purpose:'register_phone'});
      return route.fulfill({status:202,json:{challenge_id:'offline-challenge',expires_in_seconds:600}});
    }
    if (url.pathname.startsWith('/synthetic-api/')) return route.fulfill({status:503,json:{detail:'offline service fixture'}});
    return route.abort();
  });
  await page.goto('/dist/index.html');
  await expect(page.locator('#public-product-status')).toContainText('每月12积分');
  await page.locator('#nav-guest').getByRole('button',{name:'注册',exact:true}).click();
  await expect(page.locator('#auth-phone')).toBeVisible();
  await expect(page.locator('#auth-password')).toBeHidden();
  await page.locator('#auth-phone').fill('13800138000');
  await page.getByRole('button',{name:'获取验证码',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>_registerPhoneChallenge?.id)).toBe('offline-challenge');
  await page.locator('#auth-modal').getByRole('button',{name:'✕',exact:true}).click();
  await page.evaluate(()=>{
    const box=document.createElement('div');box.id='dynamic-action-test';
    box.innerHTML=`<button ${productActionAttributes('showPage','pricing')}>动态套餐入口</button>`;
    document.body.appendChild(box);
  });
  await page.getByRole('button',{name:'动态套餐入口'}).click();
  await expect(page.locator('#page-pricing')).toHaveClass(/active/);
  await page.evaluate(()=>{ switchMode('generate'); showPage('live'); });
  await expect(page.locator('#progressLabel')).toHaveText('暂无进行中的 AI 任务');
  await page.evaluate(async()=>{
    _isGenerateMode=true; _generateResult={_outcome_unknown:true,_errMsg:'原任务结果未确认'};
    await initReportPage(); await populateGenerateReport();
  });
  await expect(page.locator('#scoreRingNum')).toHaveText('--');
  await expect(page.locator('#chatEntryBanner')).toBeHidden();
  await page.evaluate(()=>{showPage('upload');switchMode('diagnose');});
  await expect(page.locator('#manual-form')).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('footer a[href="https://beian.miit.gov.cn/"]')).toBeVisible();
  expect(errors).toEqual([]);
});
