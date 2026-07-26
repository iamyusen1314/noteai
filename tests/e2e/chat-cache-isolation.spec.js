const { test, expect } = require('@playwright/test');

const OWNER_A = { id: 'synthetic-owner-a', username: 'synthetic_a' };
const OWNER_B = { id: 'synthetic-owner-b', username: 'synthetic_b' };
const CACHE_KEY = 'noteai_chat_session';
const SENTINEL = 'PRIVATE_NOTE_SENTINEL_A';

function storedChat(ownerUserId = OWNER_A.id, savedAt = Date.now()) {
  const value = {
    sessionId: 'synthetic-session-a',
    noteId: 'synthetic-note-a',
    noteTitle: SENTINEL,
    noteBody: 'private synthetic body',
    score: 66,
    version: 2,
    savedAt,
  };
  if (ownerUserId !== undefined) value.ownerUserId = ownerUserId;
  return value;
}

async function installBackendRouter(page, handler) {
  const requests = [];
  await page.route('http://127.0.0.1:8000/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ method: request.method(), path: url.pathname });
    const handled = await handler?.(route, request, url);
    if (handled) return;
    if (url.pathname.startsWith('/billing/') && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }
    await route.abort('blockedbyclient');
  });
  return requests;
}

async function openWithCache(page, cache, token = 'synthetic-token') {
  await page.addInitScript(({ cacheValue, authToken }) => {
    localStorage.clear();
    if (authToken) localStorage.setItem('noteai_token', authToken);
    if (cacheValue) localStorage.setItem('noteai_chat_session', JSON.stringify(cacheValue));
  }, { cacheValue: cache, authToken: token });
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
}

async function seedActiveChat(page, owner = OWNER_A) {
  await page.evaluate(({ ownerValue, sentinel, cacheKey, cacheValue }) => {
    _authToken = 'synthetic-active-token';
    _authUser = ownerValue;
    localStorage.setItem('noteai_token', _authToken);
    localStorage.setItem(cacheKey, JSON.stringify(cacheValue));
    _chatSessionId = cacheValue.sessionId;
    _chatParentNoteId = cacheValue.noteId;
    _chatIterCount = 2;
    _chatAttachImage = { base64: 'AAAA', dataURL: 'data:image/png;base64,AAAA', name: 'private.png' };
    _chatAttachFiles = [{ name: 'private.txt', text: 'private attachment' }];
    document.getElementById('chat-messages').textContent = sentinel;
    chatUpdateNote(sentinel, 'private synthetic body', 66, '良好', { version: 2 });
    chatRenderAttachPreview();
    document.getElementById('chat-no-session').style.display = 'none';
    document.getElementById('chat-active-area').style.display = 'flex';
  }, { ownerValue: owner, sentinel: SENTINEL, cacheKey: CACHE_KEY, cacheValue: storedChat(owner.id) });
}

async function expectChatCleared(page) {
  await expect.poll(() => page.evaluate(cacheKey => ({
    cache: localStorage.getItem(cacheKey),
    sessionId: _chatSessionId,
    noteId: _chatParentNoteId,
    version: _chatIterCount,
    image: _chatAttachImage,
    files: _chatAttachFiles.length,
    messages: document.getElementById('chat-messages').textContent,
    note: document.getElementById('chat-note-scroll').textContent.trim().replace(/\s+/g, ''),
    active: document.getElementById('chat-active-area').style.display,
    empty: document.getElementById('chat-no-session').style.display,
  }), CACHE_KEY)).toEqual({
    cache: null,
    sessionId: null,
    noteId: null,
    version: 0,
    image: null,
    files: 0,
    messages: '',
    note: '生成笔记后点击「开始对话优化」，笔记预览将显示在这里',
    active: 'none',
    empty: 'flex',
  });
}

function expectNoPaidOrMutationRequests(requests) {
  expect(requests.filter(r => r.path.includes('/analyze') || r.path.includes('/generate') || r.path.includes('/extract-screenshot'))).toEqual([]);
  expect(requests.filter(r => r.path.startsWith('/billing/') && r.method !== 'GET')).toEqual([]);
}

test('same owner restores only after delayed auth/me verification and retains a 24h owner-bound cache', async ({ page }) => {
  let releaseAuthMe;
  const requests = await installBackendRouter(page, async (route, request, url) => {
    if (url.pathname !== '/auth/me') return false;
    await new Promise(resolve => { releaseAuthMe = resolve; });
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OWNER_A) });
    return true;
  });
  await openWithCache(page, storedChat(OWNER_A.id));

  await expect.poll(() => typeof releaseAuthMe).toBe('function');
  expect(await page.locator('body').textContent()).not.toContain(SENTINEL);
  expect(await page.evaluate(() => _chatSessionId)).toBeNull();
  releaseAuthMe();

  await expect(page.locator('#chat-note-scroll')).toContainText(SENTINEL);
  await expect(page.locator('#chat-messages')).toContainText('已恢复上次对话');
  const cache = await page.evaluate(cacheKey => JSON.parse(localStorage.getItem(cacheKey)), CACHE_KEY);
  expect(cache.ownerUserId).toBe(OWNER_A.id);
  expect(cache.sessionId).toBe('synthetic-session-a');
  expectNoPaidOrMutationRequests(requests);
});

test('owner mismatch deletes account A cache before account B can see it', async ({ page }) => {
  const requests = await installBackendRouter(page, async (route, request, url) => {
    if (url.pathname !== '/auth/me') return false;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OWNER_B) });
    return true;
  });
  await openWithCache(page, storedChat(OWNER_A.id));
  await expect.poll(() => page.evaluate(() => _authUser?.id)).toBe(OWNER_B.id);
  await expectChatCleared(page);
  expect(await page.locator('body').textContent()).not.toContain(SENTINEL);
  expectNoPaidOrMutationRequests(requests);
});

for (const [label, cache] of [
  ['legacy ownerless', (() => { const value = storedChat(); delete value.ownerUserId; return value; })()],
  ['older than 24 hours', storedChat(OWNER_A.id, Date.now() - 86400001)],
]) {
  test(`${label} cache is deleted after auth/me succeeds`, async ({ page }) => {
    const requests = await installBackendRouter(page, async (route, request, url) => {
      if (url.pathname !== '/auth/me') return false;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OWNER_A) });
      return true;
    });
    await openWithCache(page, cache);
    await expect.poll(() => page.evaluate(() => _authUser?.id)).toBe(OWNER_A.id);
    await expectChatCleared(page);
    expectNoPaidOrMutationRequests(requests);
  });
}

for (const failure of ['401', '500', 'network']) {
  test(`auth/me ${failure} failure clears cache, DOM, attachments, and runtime state`, async ({ page }) => {
    const requests = await installBackendRouter(page, async (route, request, url) => {
      if (url.pathname !== '/auth/me') return false;
      if (failure === 'network') await route.abort('connectionfailed');
      else await route.fulfill({ status: Number(failure), contentType: 'application/json', body: '{}' });
      return true;
    });
    await openWithCache(page, storedChat(OWNER_A.id));
    await seedActiveChat(page);
    await page.evaluate(() => authRestoreSession());
    await expectChatCleared(page);
    expect(await page.evaluate(() => localStorage.getItem('noteai_token'))).toBeNull();
    expectNoPaidOrMutationRequests(requests);
  });
}

for (const authMode of ['login', 'register']) {
  test(`${authMode} identity change from synthetic account A to B clears all Chat user state`, async ({ page }) => {
    const requests = await installBackendRouter(page, async (route, request, url) => {
      if (url.pathname !== `/auth/${authMode}`) return false;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'synthetic-token-b', user: OWNER_B }),
      });
      return true;
    });
    await openWithCache(page, null, null);
    await seedActiveChat(page);
    await page.evaluate(mode => {
      _authTab = mode;
      document.getElementById('auth-username').value = 'synthetic_b';
      document.getElementById('auth-password').value = 'synthetic-password';
      document.getElementById('auth-email').value = (
        mode === 'register' ? '' : 'synthetic-b@example.invalid'
      );
      if (mode === 'register') {
        document.getElementById('auth-privacy-consent').checked = true;
        document.getElementById('auth-cross-border-consent').checked = true;
      }
      return doAuth();
    }, authMode);
    await expect.poll(() => page.evaluate(() => _authUser?.id)).toBe(OWNER_B.id);
    await expectChatCleared(page);
    expectNoPaidOrMutationRequests(requests);
  });
}

test('logout clears locally before the logout request completes', async ({ page }) => {
  let logoutStarted = false;
  const requests = await installBackendRouter(page, async (route, request, url) => {
    if (url.pathname !== '/auth/logout') return false;
    logoutStarted = true;
    await new Promise(() => {});
    return true;
  });
  await openWithCache(page, null, null);
  await seedActiveChat(page);
  await page.evaluate(() => { void doLogout(); });
  await expect.poll(() => logoutStarted).toBe(true);
  await expectChatCleared(page);
  expect(await page.evaluate(() => localStorage.getItem('noteai_token'))).toBeNull();
  expectNoPaidOrMutationRequests(requests);
});

for (const status of [401, 403]) {
  test(`Chat message ${status} clears cache, DOM, attachments, and runtime state`, async ({ page }) => {
    const requests = await installBackendRouter(page, async (route, request, url) => {
      if (url.pathname !== '/chat/message') return false;
      await route.fulfill({ status, contentType: 'application/json', body: '{}' });
      return true;
    });
    await openWithCache(page, null, null);
    await seedActiveChat(page);
    await page.evaluate(() => chatSendMessage({ text: 'synthetic no-AI security probe' }));
    await expectChatCleared(page);
    expect(requests.filter(r => r.path === '/chat/message')).toHaveLength(1);
    expectNoPaidOrMutationRequests(requests);
  });
}
