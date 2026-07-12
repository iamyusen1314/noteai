const { test, expect } = require('@playwright/test');

const quotaDetail = operation => ({
  operation,
  message: '测试配额不足',
  monthly_credits_remaining: 1,
  credits_balance: 0,
  credits_needed: 6,
});

async function openApp(page) {
  await page.addInitScript(() => {
    localStorage.clear();
    window.__quotaConfirmMessages = [];
    window.confirm = message => {
      window.__quotaConfirmMessages.push(String(message));
      return false;
    };
  });
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);
  await page.evaluate(() => {
    _authToken = 'route-mock-token';
    _authUser = { id: 'route-mock-user' };
  });
}

async function expectSingleQuotaPrompt(page, operationLabel) {
  await expect.poll(() => page.evaluate(() => window.__quotaConfirmMessages.length)).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__quotaConfirmMessages[0])).toContain(operationLabel);
  await expect.poll(() => page.evaluate(() => window.__quotaConfirmMessages[0])).toContain('测试配额不足');
}

test('Analyze 402 uses the shared quota prompt without a real API call', async ({ page }) => {
  let analyzeRequests = 0;
  await page.route('**/analyze/stream', async route => {
    analyzeRequests += 1;
    await route.fulfill({ status: 402, contentType: 'application/json', body: JSON.stringify({ detail: quotaDetail('analyze') }) });
  });
  await openApp(page);
  await page.evaluate(() => showPage('upload'));
  await page.locator('.input-type', { hasText: '手动填写' }).click();
  await page.locator('#inputTitle').fill('配额测试标题');
  await page.locator('#inputDesc').fill('配额测试正文');
  await page.locator('#diagnoseSubmitBtn').click();

  await expectSingleQuotaPrompt(page, 'AI深度诊断');
  expect(analyzeRequests).toBe(1);
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
});

test('Generate 402 uses the shared quota prompt without a real AI call', async ({ page }) => {
  let generateRequests = 0;
  await page.route('**/generate/stream', async route => {
    generateRequests += 1;
    await route.fulfill({ status: 402, contentType: 'application/json', body: JSON.stringify({ detail: quotaDetail('generate') }) });
  });
  await openApp(page);
  await page.evaluate(() => {
    showPage('upload');
    switchMode('generate');
  });
  await page.locator('#genBrief').fill('配额测试创作简报');
  await page.locator('#generateSubmitBtn').click();

  await expectSingleQuotaPrompt(page, 'AI爆文生成');
  expect(generateRequests).toBe(1);
  await expect(page.locator('#generateSubmitBtn')).toBeEnabled();
});

test('Chat 402 uses the shared quota prompt and restores the input', async ({ page }) => {
  let chatRequests = 0;
  await page.route('**/chat/message', async route => {
    chatRequests += 1;
    await route.fulfill({ status: 402, contentType: 'application/json', body: JSON.stringify({ detail: quotaDetail('rewrite') }) });
  });
  await openApp(page);
  await page.evaluate(() => {
    _chatSessionId = 'route-mock-session';
    showPage('chat');
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    chatSendMessage({ text: '请重写这篇笔记' });
  });

  await expectSingleQuotaPrompt(page, '对话重写');
  expect(chatRequests).toBe(1);
  await expect(page.locator('#chat-messages')).toContainText('对话深度重写积分不足');
  await expect(page.locator('#chat-input')).toBeEnabled();
});

test('Chat 404 recovery sends the retry 402 through the same quota handling', async ({ page }) => {
  let chatRequests = 0;
  let startRequests = 0;
  await page.route('**/chat/message', async route => {
    chatRequests += 1;
    if (chatRequests === 1) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'session missing' }) });
      return;
    }
    await route.fulfill({ status: 402, contentType: 'application/json', body: JSON.stringify({ detail: quotaDetail('rewrite') }) });
  });
  await page.route('**/chat/start', async route => {
    startRequests += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'recovered-session' }) });
  });
  await openApp(page);
  await page.evaluate(() => {
    _generateResult = {
      note_title: '已生成标题',
      note_body: '已生成正文',
      _domain: '美食',
    };
    _chatSessionId = 'expired-session';
    showPage('chat');
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    chatSendMessage({ text: '重建会话后继续重写' });
  });

  await expectSingleQuotaPrompt(page, '对话重写');
  expect(startRequests).toBe(1);
  expect(chatRequests).toBe(2);
  await expect(page.locator('#chat-messages')).toContainText('对话深度重写积分不足');
  await expect(page.locator('#chat-messages')).not.toContainText('服务器错误');
  await expect(page.locator('#chat-input')).toBeEnabled();
});

test('OCR 402 prompts once, marks every image failed, and keeps diagnosis gated', async ({ page }) => {
  let ocrRequests = 0;
  let validateRequests = 0;
  await page.route('**/extract-screenshot', async route => {
    ocrRequests += 1;
    await route.fulfill({ status: 402, contentType: 'application/json', body: JSON.stringify({ detail: quotaDetail('screenshot') }) });
  });
  await page.route('**/validate-ocr', async route => {
    validateRequests += 1;
    await route.abort();
  });
  await openApp(page);
  await page.evaluate(async () => {
    showPage('upload');
    const images = [
      { name: 'mock-1.png', dataURL: 'data:image/png;base64,AAAA' },
      { name: 'mock-2.png', dataURL: 'data:image/png;base64,BBBB' },
    ];
    _ssImages = images;
    _ssOcrCache = new Map();
    _ssOcrErrors = new Map();
    _ssOcrStatus = new Map();
    _renderSsThumbs();
    await _ocrImages(images);
  });

  await expectSingleQuotaPrompt(page, '截图识别');
  expect(ocrRequests).toBe(2);
  expect(validateRequests).toBe(0);
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagnoseSubmitBtn')).toContainText('2 张识别失败');
  await expect(page.locator('#ss-ocr-status')).toContainText('2/2 张失败');
  expect(await page.evaluate(() => _ssImages.every(img => _ssOcrCache.has(img.dataURL) && _ssOcrCache.get(img.dataURL) === null))).toBe(true);
});
