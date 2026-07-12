const { test, expect } = require('@playwright/test');


test('canonical chat response replaces conflicting streamed draft using text-only rendering', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');

  await page.evaluate(() => {
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    window._chatAiText = '';
    window._chatAiBubble = null;
    chatHandleEvent({type: 'content_chunk', data: '草稿声称已经删除，但仍写20分钟。'});
    chatHandleEvent({
      type: 'note_update',
      title: '最终标题',
      body: '只保留真实菜品体验。',
      score: 74.1,
      grade: '良好',
      saved_note_id: 'note-v2',
      saved_note_version: 2,
    });
    chatHandleEvent({
      type: 'canonical_response',
      status: 'saved',
      saved: true,
      title: '最终标题',
      body: '只保留真实菜品体验。',
      score: 74.1,
      grade: '良好',
      saved_note_id: 'note-v2',
      saved_note_version: 2,
    });
  });

  const bubbles = page.locator('#chat-messages .cmsg.ai .cmsg-bubble');
  await expect(bubbles.last()).not.toContainText('20分钟');
  await expect(bubbles.last()).toContainText('v2');
  await expect(page.locator('#chat-note-scroll')).toContainText('只保留真实菜品体验。');
  await expect(page.locator('#chat-note-iter')).toHaveText('第 2 版');
});


test('failed canonical chat response preserves preview and never says note was updated', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');

  await page.evaluate(() => {
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    chatUpdateNote('旧标题', '旧正文', 75.3, '优秀', {version: 1});
    window._chatAiText = '';
    window._chatAiBubble = null;
    chatHandleEvent({type: 'content_chunk', data: '草稿错误宣称已完成。'});
    chatHandleEvent({
      type: 'canonical_response',
      status: 'save_failed',
      saved: false,
      title: '旧标题',
      body: '旧正文',
      score: 75.3,
      grade: '优秀',
      saved_note_id: 'note-root',
      saved_note_version: 1,
    });
  });

  await expect(page.locator('#chat-note-scroll')).toContainText('旧正文');
  await expect(page.locator('#chat-messages')).not.toContainText('笔记已更新');
  await expect(page.locator('#chat-messages .cmsg.ai .cmsg-bubble').last()).toContainText('未保存新版本');
});


test('streamed draft is replaced by canonical result and only canonical note reaches localStorage', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(() => {
    _authUser = {id: 'synthetic-user-a'};
    _chatSessionId = 'synthetic-session-a';
    _chatParentNoteId = 'note-v1';
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    chatUpdateNote('旧正式标题', '旧正式正文', 70, '良好', {version: 1});
    const encoder = new TextEncoder();
    const bytes = encoder.encode(
      'data: {"type":"content_chunk","data":"DRAFT_SENTINEL草稿"}\r\n\r\n'
      + 'data: {"type":"note_update","title":"新正式标题","body":"CANONICAL_SENTINEL正式正文","score":75,"grade":"优秀","saved_note_id":"note-v2","saved_note_version":2}\r\n\r\n'
      + 'data: {"type":"canonical_response","status":"saved","saved":true,"title":"新正式标题","body":"CANONICAL_SENTINEL正式正文","score":75,"grade":"优秀","saved_note_id":"note-v2","saved_note_version":2}\r\n\r\n'
      + 'data: {"type":"done"}\r\n\r\n'
    );
    let requestCount = 0;
    window.fetch = async () => {
      requestCount += 1;
      window.__chatRequestCount = requestCount;
      return new Response(new ReadableStream({
        start(controller) {
          for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2));
          controller.close();
        },
      }), {status: 200, headers: {'Content-Type': 'text/event-stream'}});
    };
    chatSendMessage({text: '请重写'});
  });

  await expect.poll(() => page.evaluate(() => _chatBusy)).toBe(false);
  await expect.poll(() => page.evaluate(() => __chatRequestCount || 0)).toBe(1);
  await expect(page.locator('#chat-messages .cmsg.ai .cmsg-bubble').last()).not.toContainText('DRAFT_SENTINEL');
  await expect(page.locator('#chat-messages .cmsg.ai .cmsg-bubble').last()).toContainText('CANONICAL_SENTINEL');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('noteai_chat_session') || '')).toContain('CANONICAL_SENTINEL');
  expect(await page.evaluate(() => localStorage.getItem('noteai_chat_session') || '')).not.toContain('DRAFT_SENTINEL');
});


test('draft followed by EOF is outcome unknown and does not pollute canonical localStorage', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(() => {
    _authUser = {id: 'synthetic-user-b'};
    _chatSessionId = 'synthetic-session-b';
    _chatParentNoteId = 'note-v1';
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
    chatUpdateNote('旧正式标题', 'STORED_CANONICAL正式正文', 70, '良好', {version: 1});
    chatSaveSessionToStorage();
    const encoder = new TextEncoder();
    window.__chatRequestCount = 0;
    window.fetch = async () => {
      window.__chatRequestCount += 1;
      return new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"type":"content_chunk","data":"DRAFT_ONLY_SENTINEL"}\n\n'));
          controller.close();
        },
      }), {status: 200, headers: {'Content-Type': 'text/event-stream'}});
    };
    chatSendMessage({text: '请重写'});
  });

  await expect.poll(() => page.evaluate(() => _chatBusy)).toBe(false);
  await expect.poll(() => page.evaluate(() => __chatRequestCount || 0)).toBe(1);
  await expect(page.locator('#chat-messages')).toContainText('结果确认中');
  const stored = await page.evaluate(() => localStorage.getItem('noteai_chat_session') || '');
  expect(stored).toContain('STORED_CANONICAL');
  expect(stored).not.toContain('DRAFT_ONLY_SENTINEL');
});
