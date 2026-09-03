const { test, expect } = require('@playwright/test');


test('admin prompt preview is industry-scoped, read-only and XSS-safe', async ({ page }) => {
  const requests = [];
  const maliciousKey = 'prompt-"><img id="prompt-key-xss" src=x onerror="window.__promptPreviewXss=1">';
  const maliciousLabel = '<img id="prompt-label-xss" src=x onerror="window.__promptPreviewXss=1">Label';
  const maliciousModule = '<img id="prompt-module-xss" src=x onerror="window.__promptPreviewXss=1">Module';
  await page.route('https://cdnjs.cloudflare.com/**', route => route.abort('blockedbyclient'));
  await page.route('**/admin/prompts**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({
      method: request.method(),
      path: url.pathname,
      domain: url.searchParams.get('domain'),
      authorization: request.headers()['authorization'],
    });
    if (url.pathname === '/admin/prompts') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          prompts: [{ key: maliciousKey, label: maliciousLabel, module: maliciousModule, version: 5 }],
        }),
      });
      return;
    }
    const effectivePrefix = '/admin/prompts/';
    const isEffective = url.pathname.startsWith(effectivePrefix) && url.pathname.endsWith('/effective');
    const encodedKey = isEffective
      ? url.pathname.slice(effectivePrefix.length, -'/effective'.length)
      : url.pathname.slice(effectivePrefix.length);
    const requestKey = decodeURIComponent(encodedKey);
    if (isEffective && requestKey === maliciousKey) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          key: maliciousKey,
          domain: url.searchParams.get('domain'),
          model_strategy: 'V0.4',
          base_revision: 5,
          preview_kind: 'effective_template',
          preview_complete: false,
          rendered_text: '<img id="prompt-preview-xss" src=x onerror="window.__promptPreviewXss=1">V0.4有效模板',
          dynamic_layers: ['统一质量契约', '<img id="layer-xss" src=x>'],
          privacy_notice: '不包含用户正文、记忆、附件、内部推理或认证信息。',
        }),
      });
      return;
    }
    if (!isEffective && requestKey === maliciousKey) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          key: maliciousKey,
          label: maliciousLabel,
          module: maliciousModule,
          content: 'V0.4基础内容',
          version: 5,
          updated_at: '2026-07-12T00:00:00+00:00',
          history: [],
        }),
      });
      return;
    }
    await route.abort('blockedbyclient');
  });
  await page.addInitScript(() => {
    localStorage.clear();
    window.__promptPreviewXss = 0;
  });
  await page.goto('/model/admin.html');
  await page.evaluate(async () => {
    _adminToken = 'route-mock-admin-token';
    await loadPrompts();
    document.querySelector('.prompt-list-item').click();
  });

  await expect(page.locator('#pe-effective')).toHaveValue(/V0\.4有效模板/);
  await expect(page.locator('#pe-preview-meta')).toContainText('effective_template');
  await expect(page.locator('#pe-preview-meta')).toContainText('完整请求预览：否');
  await expect(page.locator('#pe-dynamic-layers')).toContainText('<img id="layer-xss"');
  await expect(page.locator('#pe-preview-privacy')).toContainText('不包含用户正文');
  await expect(page.locator('#prompt-preview-xss, #layer-xss, #prompt-key-xss, #prompt-label-xss, #prompt-module-xss')).toHaveCount(0);
  await expect(page.locator('#prompt-list')).toContainText(maliciousLabel);
  await expect(page.locator('#prompt-list')).toContainText(maliciousModule);
  await expect(page.locator('.prompt-list-item')).toHaveClass(/active/);
  expect(await page.evaluate(() => window.__promptPreviewXss)).toBe(0);

  await page.evaluate(() => {
    document.getElementById('pe-domain').value = '健身';
    return loadPromptPreview();
  });
  await expect.poll(() => requests.at(-1)?.domain).toBe('健身');
  expect(requests.every(item => item.method === 'GET')).toBe(true);
  expect(requests.every(item => item.authorization === 'Bearer route-mock-admin-token')).toBe(true);
  expect(requests.filter(item => /analyze|generate|chat|billing/.test(item.path))).toEqual([]);
});
