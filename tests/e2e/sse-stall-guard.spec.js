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
            if (typeof scenario.byteStream === 'string') {
              const bytes = encoder.encode(scenario.byteStream);
              const sizes = scenario.byteSizes || [1, 2, 3, 1, 4];
              let offset = 0;
              let part = 0;
              while (offset < bytes.length) {
                const size = Math.max(1, sizes[part % sizes.length]);
                const next = Math.min(bytes.length, offset + size);
                controller.enqueue(bytes.slice(offset, next));
                offset = next;
                part += 1;
              }
              if (scenario.errorAfterBytes) {
                setTimeout(() => { try { controller.error(new Error('transport failed after payload')); } catch {} }, scenario.errorAfterBytes);
              } else {
                controller.close();
              }
              return;
            }
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

  test('generate warns before first event and treats clean EOF without terminal as outcome unknown', async ({ page }) => {
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
    await expect.poll(() => page.evaluate(() => _generateResult?._outcome_unknown === true)).toBe(true);
    await expect.poll(() => page.evaluate(() => _generateResult?._errMsg || '')).toContain('结果确认中');
    await expect(page.locator('#generateSubmitBtn')).toBeEnabled();
  });

  test('chat warns during event silence without cancel or retry, then accepts done', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      _chatSessionId = 'mock-session';
      __installSseMock('/chat/message', {
        chunks: [
          {data: 'data: {"type":"typing"}\n\n'},
          // Keep the warning visible long enough for a five-worker suite to
          // observe it even when Chromium timers are heavily contended.
          {delayMs: 800, data: 'data: {"type":"done"}\n\n'},
        ],
        closeDelayMs: 10,
      });
      chatSendMessage({text: '请继续优化'});
      chatSendMessage({text: '不应重复提交'});
    });

    await expect.poll(() => page.evaluate(() => ({
      warning: (document.querySelector('[data-sse-warning="chat"]')?.textContent || '')
        .includes('任务可能仍在处理，请不要重复提交'),
      busy: _chatBusy,
      requests: __sseRequestCounts['/chat/message'] || 0,
    }))).toEqual({warning: true, busy: true, requests: 1});
    await expect.poll(() => page.evaluate(() => _chatBusy)).toBe(false);
    await expect(page.locator('[data-sse-warning="chat"]')).toHaveCount(0);
  });

  test('shared parser handles CRLF, split UTF-8 and ignores a transport error after analyze success', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      showPage('upload');
      switchMode('diagnose');
      __installSseMock('/analyze/stream', {
        byteStream: 'data: {"type":"process_update","schema_version":"process.v1","phase":"observe","agent":"visual","status_code":"material_observed","reason_codes":["material_observed"],"facts":{"image_count":1}}\r\n\r\ndata: {"type":"complete","plans":[],"score":70,"label":"中文完成"}\r\n\r\n',
        byteSizes: [1, 1, 2, 1, 3],
        errorAfterBytes: 20,
      });
    });
    await page.locator('.input-type', {hasText: '手动填写'}).click();
    await page.locator('#inputTitle').fill('多字节切片标题');
    await page.locator('#inputDesc').fill('多字节切片正文');
    await page.evaluate(() => startDiagnosis());

    await expect.poll(() => page.evaluate(() => _diagnosisStreamActive)).toBe(false);
    await expect.poll(() => page.evaluate(() => _diagnoseResult?.type || '')).toBe('complete');
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/analyze/stream'] || 0)).toBe(1);
    await expect(page.locator('#bubbleArea')).toContainText('视觉分析师');
    await expect.poll(() => page.evaluate(() => _diagnoseResult?._outcome_unknown || false)).toBe(false);
  });

  test('shared parser accepts a complete EOF tail without trailing newline', async ({ page }) => {
    await openApp(page);
    await page.evaluate(() => {
      showPage('upload');
      switchMode('generate');
      window.autoSaveGeneratedNote = async () => {};
      __installSseMock('/generate/stream', {
        byteStream: 'data: {"type":"complete","title":"EOF完成","body":"正式正文","score":72}',
        byteSizes: [1],
      });
    });
    await page.locator('#genBrief').fill('EOF 尾事件测试');
    await page.evaluate(() => startGeneration());

    await expect.poll(() => page.evaluate(() => _generateResult?.type || '')).toBe('complete');
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/generate/stream'] || 0)).toBe(1);
    await expect.poll(() => page.evaluate(() => _generateResult?._outcome_unknown || false)).toBe(false);
  });

  test('409 states use fixed messages and never echo malicious response text', async ({ page }) => {
    await openApp(page);
    const messages = await page.evaluate(async () => {
      const codes = ['IDEMPOTENCY_CONFLICT', 'IDEMPOTENCY_IN_PROGRESS', 'IDEMPOTENCY_COMPLETED', 'IDEMPOTENCY_FAILED'];
      return Promise.all(codes.map(code => paidRequest409Message(new Response(JSON.stringify({
        detail: {code, message: 'MALICIOUS_RAW_RESPONSE'},
      }), {status: 409, headers: {'Content-Type': 'application/json'}}))));
    });
    expect(messages).toHaveLength(4);
    for (const message of messages) expect(message).not.toContain('MALICIOUS_RAW_RESPONSE');
    expect(messages[0]).toContain('冲突');
    expect(messages[1]).toContain('处理中');
    expect(messages[2]).toContain('已经完成');
    expect(messages[3]).toContain('退款');
  });
});
