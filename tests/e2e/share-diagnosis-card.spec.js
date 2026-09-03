const { test, expect } = require('@playwright/test');


test('diagnosis share creates a local PNG without a supplier or API request', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(navigator, 'canShare', {
      configurable: true,
      value: undefined,
    });
  });
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.waitForLoadState('domcontentloaded');

  let captureRequests = false;
  const requestsAfterClick = [];
  page.on('request', request => {
    if (captureRequests && !request.url().startsWith('blob:')) {
      requestsAfterClick.push(request.url());
    }
  });

  await page.evaluate(() => {
    _diagnoseResult = {
      composite_score: 82,
      ces_percentile: 79,
      _domain: '旅行',
      _inputTitle: 'SENSITIVE_TITLE_MUST_NOT_BE_REQUIRED',
    };
    document.getElementById('shareCardBanner').style.display = 'block';
  });

  captureRequests = true;
  const downloadPromise = page.waitForEvent('download');
  await page.evaluate(() => (
    shareDiagnosisCard(document.querySelector('#shareCardBanner .share-btn'))
  ));
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const body = Buffer.concat(chunks);

  expect(download.suggestedFilename()).toBe('noteai-diagnosis-card.png');
  expect(body.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  expect(body.length).toBeGreaterThan(10_000);
  await expect(page.locator('#toast')).toContainText('诊断卡片 PNG 已下载');
  expect(requestsAfterClick).toEqual([]);
});
