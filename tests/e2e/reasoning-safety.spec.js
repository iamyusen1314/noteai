const { test, expect } = require('@playwright/test');

const SENTINEL = 'SEC002_BROWSER_PRIVATE_REASONING_SENTINEL';

test('legacy reasoning events are ignored while safe process facts remain visible', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect(page).toHaveTitle(/NoteAI Pro/);

  await page.evaluate((sentinel) => {
    localStorage.removeItem('noteai_chat_session');
    _handleGenStreamEvent({type: 'thinking_chunk', data: sentinel});
    chatHandleEvent({type: 'thinking_start'});
    chatHandleEvent({type: 'thinking_chunk', data: sentinel});
    chatHandleEvent({type: 'thinking_end', summary: sentinel});

    _handleGenStreamEvent({
      type: 'process_update',
      schema_version: 'process.v1',
      phase: 'decide',
      agent: 'arbiter',
      status_code: 'candidate_selection_complete',
      reason_codes: ['candidate_comparison'],
      facts: {candidate_count: 3, viable_count: 2, raw: sentinel},
      raw: sentinel,
    });
    chatHandleEvent({
      type: 'final_explanation',
      schema_version: 'process.v1',
      phase: 'save',
      agent: 'chat',
      status_code: 'note_version_saved',
      reason_codes: ['quality_gate_checked', 'note_version_saved'],
      facts: {saved: true, version: 2, provider: sentinel},
      reasoning_content: sentinel,
    });
  }, SENTINEL);

  await expect(page.locator('#bubbleArea')).toContainText('候选版本比较完成');
  await expect(page.locator('#bubbleArea')).toContainText('比较候选：3 个');
  await expect(page.locator('#chat-messages')).toContainText('新版本已安全保存');
  await expect(page.locator('#chat-messages')).toContainText('保存版本：v2');

  const exposure = await page.evaluate((sentinel) => ({
    dom: document.body.textContent.includes(sentinel),
    html: document.documentElement.innerHTML.includes(sentinel),
    storage: Object.values(localStorage).some(value => String(value).includes(sentinel)),
  }), SENTINEL);
  expect(exposure).toEqual({dom: false, html: false, storage: false});
});
