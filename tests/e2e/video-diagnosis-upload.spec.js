const { test, expect } = require('@playwright/test');

async function openVideoApp(page) {
  await page.addInitScript(() => localStorage.clear());
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);
  await page.evaluate(() => {
    _authToken = 'route-mock-token';
    _authUser = { id: 'route-mock-user' };
    showPage('upload');
    const videoTab = Array.from(document.querySelectorAll('.input-type'))
      .find(el => el.textContent.includes('视频上传'));
    selectType(videoTab, '视频上传');
    clearDiagVideo();
  });
}

async function installVideoProbe(page, mode = 'error', duration = null) {
  await page.evaluate(({ mode, duration }) => {
    if (!window.__originalCreateElement) {
      window.__originalCreateElement = document.createElement.bind(document);
    }
    window.__videoProbeMode = mode;
    window.__videoProbeDuration = duration;
    window.__videoProbeReleases = [];
    document.createElement = function patchedCreateElement(tagName, ...args) {
      if (String(tagName).toLowerCase() !== 'video') {
        return window.__originalCreateElement(tagName, ...args);
      }
      const fake = { duration: window.__videoProbeDuration };
      Object.defineProperty(fake, 'src', {
        set() {
          const release = () => {
            if (window.__videoProbeMode === 'loaded') fake.onloadedmetadata?.();
            else fake.onerror?.();
          };
          window.__videoProbeReleases.push(release);
          if (window.__videoProbeMode !== 'pending') setTimeout(release, 0);
        },
      });
      return fake;
    };
  }, { mode, duration });
}

async function startSyntheticUpload(page, name = 'tiny.mp4', bytes = [1, 2, 3]) {
  await page.evaluate(({ name, bytes }) => {
    const file = new File([new Uint8Array(bytes)], name, { type: 'video/mp4' });
    window.__diagUploadPromise = _uploadDiagVideoFile(file);
  }, { name, bytes });
}

test('video gate is mode-specific and startDiagnosis keeps a no-file second guard', async ({ page }) => {
  let analyzeRequests = 0;
  await page.route('**/analyze/stream', route => {
    analyzeRequests += 1;
    return route.abort();
  });
  await openVideoApp(page);

  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagnoseSubmitBtn')).toContainText('请先上传视频');
  await page.evaluate(() => startDiagnosis());
  expect(analyzeRequests).toBe(0);

  await page.locator('.input-type', { hasText: '手动填写' }).click();
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();

  await page.locator('.input-type', { hasText: '截图上传' }).click();
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagnoseSubmitBtn')).toContainText('请先上传截图');
});

test('preflight and upload stay gated, then ready shows honest small-file size', async ({ page }) => {
  let releaseUpload;
  const uploadGate = new Promise(resolve => { releaseUpload = resolve; });
  let uploadRequests = 0;
  await page.route('**/upload-video', async route => {
    uploadRequests += 1;
    await uploadGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ file_id: 'video-ready', filename: 'tiny.mp4', size: 3, duration_sec: 2, frames: 1 }),
    });
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'pending');
  await startSyntheticUpload(page);

  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('preflight');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagVideoStageLabel')).toContainText('检查');
  await expect(page.locator('#diagVideoSizeText')).toContainText('3 B');

  await page.evaluate(() => window.__videoProbeReleases.shift()());
  await expect.poll(() => uploadRequests).toBe(1);
  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('uploading');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  await expect(page.locator('#diagVideoStageLabel')).toContainText('上传并提取关键帧');
  await expect(page.locator('#diagVideoSizeText')).not.toContainText('0.0 MB');

  releaseUpload();
  await page.evaluate(() => window.__diagUploadPromise);
  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('ready');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
  await expect(page.locator('#diagVideoFileSize')).toContainText('3 B');
  await expect(page.locator('#diagVideoFileSize')).not.toContainText('0 MB');
  expect(await page.evaluate(() => _diagVideoFileId)).toBe('video-ready');
  expect(uploadRequests).toBe(1);
});

test('401, parse failure, HTTP failure, oversize and overlong video all stay disabled', async ({ page }) => {
  const responses = [
    { status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'unauthorized' }) },
    { status: 200, contentType: 'application/json', body: '{bad-json' },
    { status: 422, contentType: 'application/json', body: JSON.stringify({ detail: '视频解析失败' }) },
  ];
  let uploadRequests = 0;
  await page.route('**/upload-video', async route => {
    const response = responses[uploadRequests++];
    await route.fulfill(response);
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'error');

  for (let index = 0; index < responses.length; index += 1) {
    await startSyntheticUpload(page, `failure-${index}.mp4`, [index + 1]);
    await page.evaluate(() => window.__diagUploadPromise);
    await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('error');
    await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
    expect(await page.evaluate(() => _diagVideoFileId)).toBeNull();
  }

  await page.evaluate(() => {
    window.__diagUploadPromise = _uploadDiagVideoFile({
      name: 'oversize.mp4', type: 'video/mp4', size: 100 * 1024 * 1024 + 1,
    });
  });
  await page.evaluate(() => window.__diagUploadPromise);
  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('error');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();

  await installVideoProbe(page, 'loaded', 91);
  await startSyntheticUpload(page, 'overlong.mp4', [9]);
  await page.evaluate(() => window.__diagUploadPromise);
  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('error');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  expect(uploadRequests).toBe(3);
});

test('removing during upload invalidates the late response', async ({ page }) => {
  let releaseUpload;
  const uploadGate = new Promise(resolve => { releaseUpload = resolve; });
  let uploadRequests = 0;
  await page.route('**/upload-video', async route => {
    uploadRequests += 1;
    await uploadGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ file_id: 'stale-after-remove', filename: 'old.mp4', size: 8, duration_sec: 2, frames: 1 }),
    });
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'error');
  await startSyntheticUpload(page, 'old.mp4', [1]);
  await expect.poll(() => uploadRequests).toBe(1);
  await page.evaluate(() => clearDiagVideo());

  await expect.poll(() => page.evaluate(() => _diagVideoState)).toBe('idle');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
  releaseUpload();
  await page.evaluate(() => window.__diagUploadPromise);
  expect(await page.evaluate(() => _diagVideoFileId)).toBeNull();
  expect(await page.evaluate(() => _diagVideoFileName)).toBe('');
  await expect(page.locator('#diagVideoPreview')).toBeHidden();
  expect(uploadRequests).toBe(1);
});

test('a newer video selection wins when an older response arrives late', async ({ page }) => {
  let releaseOld;
  const oldGate = new Promise(resolve => { releaseOld = resolve; });
  let uploadRequests = 0;
  await page.route('**/upload-video', async route => {
    const requestNumber = ++uploadRequests;
    if (requestNumber === 1) await oldGate;
    const isOld = requestNumber === 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        file_id: isOld ? 'old-file-id' : 'new-file-id',
        filename: isOld ? 'old.mp4' : 'new.mp4',
        size: isOld ? 5 : 7,
        duration_sec: 2,
        frames: 1,
      }),
    });
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'error');

  await startSyntheticUpload(page, 'old.mp4', [1]);
  await expect.poll(() => uploadRequests).toBe(1);
  await page.evaluate(() => { window.__oldUploadPromise = window.__diagUploadPromise; });
  await startSyntheticUpload(page, 'new.mp4', [2]);
  await expect.poll(() => uploadRequests).toBe(2);
  await page.evaluate(() => window.__diagUploadPromise);
  expect(await page.evaluate(() => _diagVideoFileId)).toBe('new-file-id');
  await expect(page.locator('#diagVideoFileName')).toHaveText('new.mp4');

  releaseOld();
  await page.evaluate(() => window.__oldUploadPromise);
  expect(await page.evaluate(() => _diagVideoFileId)).toBe('new-file-id');
  await expect(page.locator('#diagVideoFileName')).toHaveText('new.mp4');
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
  expect(uploadRequests).toBe(2);
});

test('leaving video mode cancels pending uploads without changing ready-video retention', async ({ page }) => {
  const releases = [];
  let uploadRequests = 0;
  await page.route('**/upload-video', async route => {
    const requestNumber = ++uploadRequests;
    if (requestNumber <= 2) {
      await new Promise(resolve => { releases[requestNumber - 1] = resolve; });
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        file_id: `stale-${requestNumber}`,
        filename: `stale-${requestNumber}.mp4`,
        size: requestNumber,
        duration_sec: 2,
        frames: 1,
      }),
    });
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'error');

  await startSyntheticUpload(page, 'manual-stale.mp4', [1]);
  await expect.poll(() => uploadRequests).toBe(1);
  await page.locator('.input-type', { hasText: '手动填写' }).click();
  releases[0]();
  await page.evaluate(() => window.__diagUploadPromise);
  expect(await page.evaluate(() => ({ state: _diagVideoState, fileId: _diagVideoFileId, name: _diagVideoFileName })))
    .toEqual({ state: 'idle', fileId: null, name: '' });
  await expect(page.locator('#diagVideoPreview')).toBeHidden();

  await page.locator('.input-type', { hasText: '视频上传' }).click();
  await startSyntheticUpload(page, 'screenshot-stale.mp4', [2]);
  await expect.poll(() => uploadRequests).toBe(2);
  await page.locator('.input-type', { hasText: '截图上传' }).click();
  releases[1]();
  await page.evaluate(() => window.__diagUploadPromise);
  expect(await page.evaluate(() => ({ state: _diagVideoState, fileId: _diagVideoFileId, name: _diagVideoFileName })))
    .toEqual({ state: 'idle', fileId: null, name: '' });
  await expect(page.locator('#diagVideoPreview')).toBeHidden();

  await page.locator('.input-type', { hasText: '视频上传' }).click();
  await startSyntheticUpload(page, 'ready-retained.mp4', [3]);
  await page.evaluate(() => window.__diagUploadPromise);
  expect(await page.evaluate(() => ({ state: _diagVideoState, fileId: _diagVideoFileId })))
    .toEqual({ state: 'ready', fileId: 'stale-3' });
  await page.locator('.input-type', { hasText: '手动填写' }).click();
  expect(await page.evaluate(() => ({ state: _diagVideoState, fileId: _diagVideoFileId })))
    .toEqual({ state: 'ready', fileId: 'stale-3' });
  await page.locator('.input-type', { hasText: '视频上传' }).click();
  await expect(page.locator('#diagVideoPreview')).toBeVisible();
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
  expect(uploadRequests).toBe(3);
});

test('ready video submits exactly one analyze request with its file id', async ({ page }) => {
  let uploadRequests = 0;
  let analyzeRequests = 0;
  let analyzeBody = null;
  await page.route('**/upload-video', async route => {
    uploadRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ file_id: 'ready-submit-id', filename: 'ready.mp4', size: 9, duration_sec: 2, frames: 1 }),
    });
  });
  await page.route('**/analyze/stream', async route => {
    analyzeRequests += 1;
    analyzeBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'data: {"type":"complete","plans":[],"score":70}\n\ndata: [DONE]\n\n',
    });
  });
  await openVideoApp(page);
  await installVideoProbe(page, 'error');
  await startSyntheticUpload(page, 'ready.mp4', [9]);
  await page.evaluate(() => window.__diagUploadPromise);
  await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();

  await page.locator('#diagnoseSubmitBtn').click();
  await expect.poll(() => analyzeRequests).toBe(1);
  expect(analyzeBody).toMatchObject({ input_mode: 'video', video_file_id: 'ready-submit-id' });
  expect(uploadRequests).toBe(1);
  await expect.poll(() => page.evaluate(() => _diagnosisStreamActive)).toBe(false);
  expect(analyzeRequests).toBe(1);
});
