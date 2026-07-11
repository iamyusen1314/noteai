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
