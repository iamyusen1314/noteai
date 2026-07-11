const { test, expect } = require('@playwright/test');

async function openApp(page) {
  await page.addInitScript(() => {
    globalThis.__NOTEAI_SSE_WARNING_THRESHOLDS__ = {
      connectMs: 30,
      firstEventMs: 30,
      idleMs: 30,
      pollMs: 10,
    };
  });
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);
  await page.evaluate(() => {
    const nativeFetch = window.fetch.bind(window);
    window.__sseRequestCounts = {};
    window.__installSseMock = (path, scenario) => {
      window.fetch = async (url, options) => {
        if (!String(url).includes(path)) return nativeFetch(url, options);
        window.__sseRequestCounts[path] = (window.__sseRequestCounts[path] || 0) + 1;
        if (scenario.connectDelayMs) {
          await new Promise(resolve => setTimeout(resolve, scenario.connectDelayMs));
        }
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            let elapsed = 0;
            for (const chunk of scenario.chunks || []) {
              elapsed += chunk.delayMs || 0;
              setTimeout(() => controller.enqueue(encoder.encode(chunk.data)), elapsed);
            }
            setTimeout(() => controller.close(), elapsed + (scenario.closeDelayMs || 0));
          },
        });
        return new Response(stream, {status: 200, headers: {'Content-Type': 'text/event-stream'}});
      };
    };
  });
}

test.describe('SSE warning-only guard', () => {
  test('analyze warns on slow connection, keeps one request, then clears on terminal', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      showPage('upload');
      switchMode('diagnose');
      __installSseMock('/analyze/stream', {
        connectDelayMs: 180,
        chunks: [{data: 'data: {"type":"complete","plans":[],"score":70}\n\n'}],
        closeDelayMs: 10,
      });
    });
    await page.locator('.input-type', {hasText: '手动填写'}).click();
    await page.locator('#inputTitle').fill('慢连接测试标题');
    await page.locator('#inputDesc').fill('慢连接测试正文');
    await page.evaluate(() => { startDiagnosis(); startDiagnosis(); });

    await expect(page.locator('[data-sse-warning="analyze"]')).toContainText('任务可能仍在处理，请不要重复提交');
    await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/analyze/stream'] || 0)).toBe(1);
    await expect.poll(() => page.evaluate(() => _diagnosisStreamActive)).toBe(false);
    await expect(page.locator('[data-sse-warning="analyze"]')).toHaveCount(0);
    await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
  });

  test('generate warns before first event and treats clean EOF without terminal as error', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      showPage('upload');
      switchMode('generate');
      __installSseMock('/generate/stream', {chunks: [], closeDelayMs: 180});
    });
    await page.locator('#genBrief').fill('无终态 EOF 测试简报');
    await page.evaluate(() => { startGeneration(); startGeneration(); });

    await expect(page.locator('[data-sse-warning="generate"]')).toContainText('任务可能仍在处理，请不要重复提交');
    await expect(page.locator('#generateSubmitBtn')).toBeDisabled();
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/generate/stream'] || 0)).toBe(1);
    await expect.poll(() => page.evaluate(() => _generateResult?._error === true)).toBe(true);
    await expect.poll(() => page.evaluate(() => _generateResult?._errMsg || '')).toContain('未收到完成状态');
    await expect(page.locator('#generateSubmitBtn')).toBeEnabled();
  });

  test('chat warns during event silence without cancel or retry, then accepts done', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      _chatSessionId = 'mock-session';
      __installSseMock('/chat/message', {
        chunks: [
          {data: 'data: {"type":"typing"}\n\n'},
          {delayMs: 180, data: 'data: {"type":"done"}\n\n'},
        ],
        closeDelayMs: 10,
      });
      chatSendMessage({text: '请继续优化'});
      chatSendMessage({text: '不应重复提交'});
    });

    await expect(page.locator('[data-sse-warning="chat"]')).toContainText('任务可能仍在处理，请不要重复提交');
    await expect.poll(() => page.evaluate(() => _chatBusy)).toBe(true);
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/chat/message'] || 0)).toBe(1);
    await expect.poll(() => page.evaluate(() => _chatBusy)).toBe(false);
    await expect(page.locator('[data-sse-warning="chat"]')).toHaveCount(0);
  });
});
