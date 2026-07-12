const { test, expect } = require('@playwright/test');

async function openScreenshotApp(page) {
  await page.addInitScript(() => localStorage.clear());
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);
  await page.evaluate(() => {
    _authToken = 'route-mock-token';
    _authUser = { id: 'route-mock-user' };
    showPage('upload');
    resetScreenshot();
  });
}

const successResult = (title, body) => ({ type: 'A', title, body, tags: '', domain: '美食' });

test('reset during delayed FileReader invalidates the selection before upload starts', async ({ page }) => {
  let extractRequests = 0;
  await page.route('**/extract-screenshot', async route => {
    extractRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(successResult('不应上传', '不应上传正文')),
    });
  });
  await openScreenshotApp(page);

  await page.evaluate(() => {
    window.__originalFileReader = window.FileReader;
    window.FileReader = class DelayedFileReader {
      readAsDataURL() {
        window.__releaseDelayedFileReader = () => this.onload({ target: { result: 'data:image/png;base64,LATE' } });
      }
    };
    const file = new File([new Uint8Array([1])], 'late.png', { type: 'image/png' });
    window.__lateSelectionDone = false;
    _addSsFiles([file]).finally(() => { window.__lateSelectionDone = true; });
    resetScreenshot();
    window.__releaseDelayedFileReader();
    window.FileReader = window.__originalFileReader;
  });

  await expect.poll(() => page.evaluate(() => window.__lateSelectionDone)).toBe(true);
  expect(await page.evaluate(() => _ssImages.length)).toBe(0);
  expect(await page.evaluate(() => _ssOcrCache.size)).toBe(0);
  await expect(page.locator('#screenshot-result')).toBeHidden();
  expect(extractRequests).toBe(0);
});

test('a later file selection supersedes an older delayed FileReader selection', async ({ page }) => {
  let extractRequests = 0;
  await page.route('**/extract-screenshot', async route => {
    extractRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(successResult('新选择', '新选择正文')),
    });
  });
  await openScreenshotApp(page);

  await page.evaluate(() => {
    window.__originalFileReader = window.FileReader;
    window.__delayedReaders = [];
    window.FileReader = class DelayedFileReader {
      readAsDataURL(file) {
        const dataURL = `data:image/png;base64,${file.name === 'new.png' ? 'NEW' : 'OLD'}`;
        window.__delayedReaders.push(() => this.onload({ target: { result: dataURL } }));
      }
    };
    const oldFile = new File([new Uint8Array([1])], 'old.png', { type: 'image/png' });
    const newFile = new File([new Uint8Array([2])], 'new.png', { type: 'image/png' });
    window.__oldSelectionDone = false;
    window.__newSelectionDone = false;
    _addSsFiles([oldFile]).finally(() => { window.__oldSelectionDone = true; });
    _addSsFiles([newFile]).finally(() => { window.__newSelectionDone = true; });
    window.__delayedReaders[1]();
  });

  await expect.poll(() => page.evaluate(() => window.__newSelectionDone)).toBe(true);
  await expect.poll(() => extractRequests).toBe(1);
  await page.evaluate(() => {
    window.__delayedReaders[0]();
    window.FileReader = window.__originalFileReader;
  });
  await expect.poll(() => page.evaluate(() => window.__oldSelectionDone)).toBe(true);
  expect(await page.evaluate(() => _ssImages.map(img => img.name))).toEqual(['new.png']);
  expect(extractRequests).toBe(1);
});

test('adding an image after a completed batch immediately replaces the stale completed status', async ({ page }) => {
  let releaseExtract;
  const extractGate = new Promise(resolve => { releaseExtract = resolve; });
  let extractRequests = 0;
  await page.route('**/extract-screenshot', async route => {
    extractRequests += 1;
    await extractGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(successResult('第二图', '第二图正文')),
    });
  });
  await page.route('**/validate-ocr', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ title: '合并标题', body: '合并正文', tags: '', domain: '美食', validated: true, char_count: 4 }),
  }));
  await openScreenshotApp(page);

  await page.evaluate(async () => {
    const first = { name: 'first.png', dataURL: 'data:image/png;base64,AAAA' };
    _ssImages = [first];
    _ssOcrCache = new Map([[first.dataURL, { type: 'A', title: '第一图', body: '第一图正文' }]]);
    _ssOcrErrors = new Map();
    _ssOcrStatus = new Map();
    _setSsImageStatus(first, 'done', '识别完成', _ssOcrCache.get(first.dataURL));
    _mergeAndShowOcrResults();
    const file = new File([new Uint8Array([1, 2, 3])], 'second.png', { type: 'image/png' });
    await _addSsFiles([file]);
  });

  await expect.poll(() => page.evaluate(() => _getScreenshotRecognitionState())).toEqual({
    total: 2, completed: 1, ok: 1, failed: 0, pending: 1,
  });
  await expect(page.locator('#ss-ocr-status')).toContainText('1/2');
  await expect(page.locator('#ss-ocr-status')).not.toContainText('完成');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagnoseSubmitBtn')).toContainText('识别中 1/2');

  releaseExtract();
  await expect(page.locator('#ss-ocr-status')).toContainText('2 张图片');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
  expect(extractRequests).toBe(1);
});

test('a stale validation response cannot complete or overwrite a newer image batch', async ({ page }) => {
  let releaseFirstValidation;
  const firstValidationGate = new Promise(resolve => { releaseFirstValidation = resolve; });
  let releaseExtract;
  const extractGate = new Promise(resolve => { releaseExtract = resolve; });
  let validationRequests = 0;
  await page.route('**/validate-ocr', async route => {
    validationRequests += 1;
    if (validationRequests === 1) await firstValidationGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        title: validationRequests === 1 ? '旧两图合并' : '当前三图合并',
        body: '合并正文', tags: '', domain: '美食', validated: true, char_count: 4,
      }),
    });
  });
  await page.route('**/extract-screenshot', async route => {
    await extractGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(successResult('第三图', '第三图正文')),
    });
  });
  await openScreenshotApp(page);

  await page.evaluate(async () => {
    const first = { name: 'first.png', dataURL: 'data:image/png;base64,AAAA' };
    const second = { name: 'second.png', dataURL: 'data:image/png;base64,BBBB' };
    _ssImages = [first, second];
    _ssOcrCache = new Map([
      [first.dataURL, { type: 'A', title: '第一图', body: '第一图正文', tags: '', domain: '美食' }],
      [second.dataURL, { type: 'A', title: '第二图', body: '第二图正文', tags: '', domain: '美食' }],
    ]);
    _ssOcrErrors = new Map();
    _ssOcrStatus = new Map();
    _setSsImageStatus(first, 'done');
    _setSsImageStatus(second, 'done');
    window.__staleValidation = _validateAndMergeOcr(Array.from(_ssOcrCache.values()));
  });
  await expect.poll(() => validationRequests).toBe(1);
  await page.evaluate(async () => {
    const file = new File([new Uint8Array([3])], 'third.png', { type: 'image/png' });
    await _addSsFiles([file]);
  });

  releaseFirstValidation();
  await expect.poll(() => page.evaluate(() => _ssOcrValidating)).toBe(false);
  await expect(page.locator('#ss-ocr-status')).toContainText('2/3');
  await expect(page.locator('#ss-ocr-status')).not.toContainText('完成');
  await expect(page.locator('#ss-title-display')).not.toHaveText('旧两图合并');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();

  releaseExtract();
  await expect.poll(() => validationRequests).toBe(2);
  await expect(page.locator('#ss-title-display')).toHaveText('当前三图合并');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
});

test('late extraction responses stay invalid after remove and reset', async ({ page }) => {
  const release = [];
  const gates = [0, 1].map(index => new Promise(resolve => { release[index] = resolve; }));
  let requestIndex = 0;
  await page.route('**/extract-screenshot', async route => {
    const index = requestIndex++;
    await gates[index];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(successResult(`迟到图${index + 1}`, '迟到正文')),
    });
  });
  await openScreenshotApp(page);

  await page.evaluate(async () => {
    const file = new File([new Uint8Array([1])], 'remove.png', { type: 'image/png' });
    await _addSsFiles([file]);
    window.__removedDataUrl = _ssImages[0].dataURL;
    _removeSsImage(0);
  });
  release[0]();
  await expect.poll(() => page.evaluate(() => _ssImages.length)).toBe(0);
  await expect(page.locator('#screenshot-result')).toBeHidden();
  expect(await page.evaluate(() => _ssOcrCache.has(window.__removedDataUrl))).toBe(false);

  await page.evaluate(async () => {
    const file = new File([new Uint8Array([2])], 'reset.png', { type: 'image/png' });
    await _addSsFiles([file]);
    window.__resetDataUrl = _ssImages[0].dataURL;
    resetScreenshot();
  });
  release[1]();
  await expect.poll(() => page.evaluate(() => _ssImages.length)).toBe(0);
  await expect(page.locator('#screenshot-result')).toBeHidden();
  expect(await page.evaluate(() => _ssOcrCache.has(window.__resetDataUrl))).toBe(false);
  expect(requestIndex).toBe(2);
});

test('mixed OCR results show the terminal failure count and keep diagnosis gated', async ({ page }) => {
  let requests = 0;
  await page.route('**/extract-screenshot', async route => {
    requests += 1;
    if (requests === 1) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(successResult('成功图', '成功正文')) });
      return;
    }
    await route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: '合成识别失败' }) });
  });
  await openScreenshotApp(page);
  await page.evaluate(async () => {
    const images = [
      { name: 'ok.png', dataURL: 'data:image/png;base64,AAAA' },
      { name: 'failed.png', dataURL: 'data:image/png;base64,BBBB' },
    ];
    _ssImages = images;
    _ssOcrCache = new Map();
    _ssOcrErrors = new Map();
    _ssOcrStatus = new Map();
    await _ocrImages(images);
  });

  await expect(page.locator('#ss-ocr-status')).toContainText('1/2 张失败');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagnoseSubmitBtn')).toContainText('1 张识别失败');
  expect(requests).toBe(2);
});
