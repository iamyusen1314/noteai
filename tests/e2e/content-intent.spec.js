const { test, expect } = require('@playwright/test');

async function openUploadPage(page) {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);
  await page.evaluate(() => showPage('upload'));
  await expect(page.locator('#contentIntentSection')).toBeVisible();
}

test.describe('content intent controls', () => {
  test('笔记类型和商家展示策略是真实可交互状态', async ({ page }) => {
    await openUploadPage(page);

    await expect(page.locator('.intent-card[data-intent="真实种草型"]')).toHaveClass(/on/);
    await expect(page.locator('.merchant-vis[data-visibility="auto"]')).toHaveClass(/on/);

    await page.locator('.intent-card[data-intent="决策转化型"]').click();
    await expect(page.locator('.intent-card[data-intent="决策转化型"]')).toHaveClass(/on/);
    await expect(page.locator('#intentHint')).toContainText('优先查可用事实源');

    await page.locator('.merchant-vis[data-visibility="show"]').click();
    await expect(page.locator('.merchant-vis[data-visibility="show"]')).toHaveClass(/on/);
    await expect(page.locator('#intentHint')).toContainText('当前要求展示商家');

    await page.locator('#merchantNameInput').fill('长禧家珑厨万博广晟店');
    const payload = await page.evaluate(() => getContentIntentPayload());
    expect(payload).toEqual({
      content_intent: '决策转化型',
      merchant_visibility: 'show',
      merchant_name: '长禧家珑厨万博广晟店',
      fact_source_policy: 'auto',
    });

    const needsSupplement = await page.evaluate(() => (
      shouldAskMerchantBeforeRun('美食', '', '龙虾乌冬汤很浓，适合到店决策', getContentIntentPayload())
    ));
    expect(needsSupplement).toBe(false);
  });

  test('决策转化型缺商家名会前置拦截，不会直接请求后端', async ({ page }) => {
    await openUploadPage(page);

    await page.locator('.intent-card[data-intent="决策转化型"]').click();
    await page.locator('.merchant-vis[data-visibility="show"]').click();

    const needsSupplement = await page.evaluate(() => (
      shouldAskMerchantBeforeRun('美食', '', '需要到店决策信息，但没有店名', getContentIntentPayload())
    ));
    expect(needsSupplement).toBe(true);
  });

  test('爆文生成请求会携带创作方向字段', async ({ page }) => {
    await openUploadPage(page);
    await page.evaluate(() => switchMode('generate'));

    await page.locator('.intent-card[data-intent="清单攻略型"]').click();
    await page.locator('.merchant-vis[data-visibility="hide"]').click();
    await page.locator('#genBrief').fill('广州日料多图素材，包含龙虾乌冬、海胆甜虾丼、鱼生和小聚场景。');

    let requestBody = null;
    await page.route('**/generate/stream', async route => {
      requestBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          'data: {"type":"complete","title":"广州日料这样点","body":"测试正文","score":72,"plans":[]}',
          '',
          'data: [DONE]',
          '',
        ].join('\n'),
      });
    });

    await page.getByRole('button', { name: /AI 生成爆文/ }).click();
    await expect.poll(() => requestBody).not.toBeNull();

    expect(requestBody).toMatchObject({
      domain: '美食',
      content_intent: '清单攻略型',
      merchant_visibility: 'hide',
      merchant_name: null,
      fact_source_policy: 'auto',
    });
    expect(requestBody.brief).toContain('龙虾乌冬');
  });

  test('诊断和生成快速双击只发送一次请求并在流结束后恢复按钮', async ({ page }) => {
    await openUploadPage(page);

    let generateRequests = 0;
    await page.route('**/generate/stream', async route => {
      generateRequests += 1;
      await new Promise(resolve => setTimeout(resolve, 150));
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: [DONE]\n\n',
      });
    });

    await page.evaluate(() => switchMode('generate'));
    await page.locator('#genBrief').fill('用于验证重复提交保护的测试简报');
    await page.evaluate(() => {
      startGeneration();
      startGeneration();
    });

    const generateBtn = page.locator('#generateSubmitBtn');
    await expect(generateBtn).toBeDisabled();
    await expect(generateBtn).toHaveAttribute('aria-busy', 'true');
    await expect.poll(() => generateRequests).toBe(1);
    await expect(generateBtn).toBeEnabled();
    await expect(generateBtn).toHaveAttribute('aria-disabled', 'false');
    await expect(generateBtn).toHaveAttribute('aria-busy', 'false');

    let analyzeRequests = 0;
    await page.route('**/analyze/stream', async route => {
      analyzeRequests += 1;
      await new Promise(resolve => setTimeout(resolve, 150));
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: [DONE]\n\n',
      });
    });

    await page.evaluate(() => switchMode('diagnose'));
    await page.locator('.input-type', { hasText: '手动填写' }).click();
    await page.locator('#inputTitle').fill('重复提交保护测试标题');
    await page.locator('#inputDesc').fill('重复提交保护测试正文');
    await page.evaluate(() => {
      startDiagnosis();
      startDiagnosis();
    });

    const diagnoseBtn = page.locator('#diagnoseSubmitBtn');
    await expect(diagnoseBtn).toBeDisabled();
    await expect(diagnoseBtn).toHaveAttribute('aria-busy', 'true');
    await expect.poll(() => analyzeRequests).toBe(1);
    await expect(diagnoseBtn).toBeEnabled();
    await expect(diagnoseBtn).toHaveAttribute('aria-disabled', 'false');
    await expect(diagnoseBtn).toHaveAttribute('aria-busy', 'false');
  });
});
