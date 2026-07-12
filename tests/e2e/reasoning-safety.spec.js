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

test('model-authored HTML stays literal while limited chat formatting remains', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  const sentinel = 'SEC003_DOM_SENTINEL';
  const malicious = `<script>window.${sentinel}=1</script><img src=x onerror="window.${sentinel}=2"><svg onload="window.${sentinel}=3"></svg><a href="javascript:window.${sentinel}=4">raw link</a><unknown-tag onclick="window.${sentinel}=5">unknown</unknown-tag>`;

  await page.evaluate(async ({ sentinel, malicious }) => {
    window[sentinel] = 0;
    addBubble(`agent ${malicious}`, `bubble ${malicious}`, 0, 0, 0);
    chatAppendAi(`${malicious}\n**粗体保留**\n\`代码保留\`\n- 列表保留`);
    renderAgentResults([{
      role: `诊断角色 ${malicious}`,
      opinion: `诊断意见 ${malicious}`,
      reason: `理由 ${malicious}`,
      evidence: [`证据 ${malicious}`],
      suggestions: [`建议 ${malicious}`],
      confidence: 0.8,
    }], malicious);
    _diagnosePromise = null;
    _generateResult = {
      note_title: '安全标题',
      note_body: '安全正文',
      title_variants: [`变体 ${malicious}`],
      ces_percentile: 70,
      grade: '良好',
      feature_hits: {},
      expert_opinions: [{
        role: `生成角色 ${malicious}`,
        opinion: `生成意见 ${malicious}`,
        reason: `生成理由 ${malicious}`,
        evidence: [`生成证据 ${malicious}`],
        suggestions: [`生成建议 ${malicious}`],
        confidence: 0.9,
      }],
    };
    await populateGenerateReport();
  }, { sentinel, malicious });

  await page.waitForTimeout(100);
  expect(await page.evaluate(s => window[s], sentinel)).toBe(0);
  await expect(page.locator('#bubbleArea')).toContainText('<img src=x onerror=');
  await expect(page.locator('#chat-messages')).toContainText('<svg onload=');
  await expect(page.locator('#chat-messages strong')).toHaveText('粗体保留');
  await expect(page.locator('#chat-messages code')).toHaveText('代码保留');
  await expect(page.locator('#chat-messages')).toContainText('• 列表保留');
  await expect(page.locator('#genVariantsList')).toContainText('<unknown-tag onclick=');
  await expect(page.locator('#genAgentResultsList')).toContainText('<script>');
  await expect(page.locator('#agentResultsList')).toContainText('<a href=');
  expect(await page.locator('#chat-messages a, #bubbleArea img, #bubbleArea svg, #genVariantsList unknown-tag, #genAgentResultsList script, #agentResultsList a').count()).toBe(0);
});
