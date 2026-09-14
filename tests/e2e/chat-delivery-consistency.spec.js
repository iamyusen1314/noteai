const { test, expect } = require('./offline-fixture');


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


test('opening an unscored note clears the previous artifact gauge', async ({page}) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(() => {
    document.getElementById('chat-active-area').style.display = 'flex';
    chatUpdateNote('已评分', '本人旧版本', 75.3, '优秀', {version:1});
    chatUpdateNote('未评分', '另一版本', null, '', {version:1});
  });
  await expect(page.locator('#chat-gauge-text')).toHaveText('—');
  await expect(page.locator('#chat-score-grade')).toHaveText('暂无已保存评分');
  expect(await page.locator('#chat-gauge-fill').evaluate(el => Number(el.style.strokeDashoffset))).toBeCloseTo(2*Math.PI*23, 2);
});

test('generation saves only its original account once and preserves a zero score', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  const result = await page.evaluate(async () => {
    _authUser = {id: 'synthetic-generation-owner'}; _authToken = 'synthetic-only';
    const identity = _chatIdentitySnapshot();
    const generated = {note_title: '原素材标题', note_body: '原素材正文', ces_percentile: 0};
    let requests = 0, sent;
    window.fetch = async (_url, init) => { requests++; sent = JSON.parse(init.body);
      return new Response(JSON.stringify({id: 'synthetic-note', version: 1}), {status: 200}); };
    await autoSaveGeneratedNote(generated, identity, 'synthetic-only');
    await autoSaveGeneratedNote(generated, identity, 'synthetic-only');
    return {requests, score: sent.score, status: generated._save_status, id: generated._saved_note_id};
  });
  expect(result).toEqual({requests: 1, score: 0, status: 'saved', id: 'synthetic-note'});
});

for (const responseCase of ['disconnect', 'server_error', 'incomplete_receipt']) {
  test(`generation preserves content and does not repeat uncertain save: ${responseCase}`, async ({ page }) => {
    await page.goto('/NoteAI_Pro_Demo_Framer.html');
    const result = await page.evaluate(async (responseCase) => {
      _authUser = {id: 'synthetic-generation-owner'}; _authToken = 'synthetic-only';
      const identity = _chatIdentitySnapshot();
      const generated = {note_title: '保留标题', note_body: '保留正文'};
      let requests = 0;
      window.fetch = async () => {
        requests++;
        if (responseCase === 'disconnect') throw new TypeError('synthetic disconnect');
        return new Response('{}', {status: responseCase === 'server_error' ? 500 : 200});
      };
      await autoSaveGeneratedNote(generated, identity, 'synthetic-only');
      await autoSaveGeneratedNote(generated, identity, 'synthetic-only');
      return {requests, body: generated.note_body, status: generated._save_status,
        saved: !!generated._saved_note_id, message: generated._save_message};
    }, responseCase);
    expect(result).toMatchObject({requests: 1, body: '保留正文', status: 'unknown', saved: false});
    expect(result.message).toContain('先查看笔记库');
    await expect(page.locator('#bubbleArea')).not.toContainText('生成结果已保存');
  });
}

test('a changed account cannot save or receive a delayed generation result', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  const result = await page.evaluate(async () => {
    _authUser = {id: 'synthetic-generation-owner'}; _authToken = 'synthetic-a';
    const identity = _chatIdentitySnapshot();
    let requests = 0;
    window.fetch = async () => { requests++; return new Response('{}'); };
    _generateResult = {note_title: 'PRIVATE_SENTINEL', note_body: '旧账户素材'};
    document.getElementById('genMainTitle').textContent = 'PRIVATE_SENTINEL';
    chatClearUserState();
    _authUser = {id: 'synthetic-other-owner'}; _authToken = 'synthetic-b';
    await autoSaveGeneratedNote({note_title:'PRIVATE_SENTINEL', note_body:'旧账户素材'}, identity, 'synthetic-a');
    _handleGenStreamEvent({type: 'complete'}, () => _chatIdentityMatches(identity));
    return {requests, generated: _generateResult};
  });
  expect(result).toEqual({requests: 0, generated: null});
  await expect(page.locator('#genMainTitle')).not.toContainText('PRIVATE_SENTINEL');
  await expect(page.locator('#genReportBody')).toBeHidden();
});

test('library chat restores its own confirmation without importing another upload form', async ({ page }) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(async () => {
    _authToken = 'synthetic-library-token';
    _authUser = {id:'synthetic-library-owner'};
    _authVerifiedOwnerId = _authUser.id;
    document.getElementById('merchantNameInput').value = 'OTHER_MERCHANT_SENTINEL';
    document.querySelectorAll('.c-tag').forEach(el => el.classList.add('on'));
    window.__libraryRequests = [];
    window.fetch = async (url, opts = {}) => {
      if (String(url).endsWith('/chat/start')) {
        window.__libraryRequests.push(JSON.parse(opts.body));
        return new Response(JSON.stringify({session_id:'synthetic-library-chat',current_score:73,
          grade:'良好',welcome:'原说明已恢复',confirmed_facts:[{question_id:'drink',question:'套餐饮品？',
            answer:'2杯拿铁',merchant:'本笔记商家',object:'9月双人套餐',time_range:'9月',status:'confirmed'}]}),
          {status:200,headers:{'Content-Type':'application/json'}});
      }
      return new Response('{}',{status:200,headers:{'Content-Type':'application/json'}});
    };
    _noteDetailData = {id:'synthetic-original-note',title:'已保存标题',body:'已保存正文',domain:'美食',score:73,version:1};
    await startChatFromLibrary();
  });
  const requests = await page.evaluate(() => window.__libraryRequests);
  expect(requests).toHaveLength(1);
  expect(requests[0].note_id).toBe('synthetic-original-note');
  expect(requests[0].user_constraints).toBeNull();
  for (const key of ['merchant_name','merchant_visibility','content_intent','fact_source_policy']) {
    expect(requests[0]).not.toHaveProperty(key);
  }
  await page.getByRole('button',{name:'查看或纠正本次商家确认',exact:true}).click();
  await expect(page.getByPlaceholder('填写更正后的完整说明')).toHaveValue('2杯拿铁');
  await expect(page.locator('#chat-messages')).toContainText('本笔记商家');
  await expect(page.locator('#chat-messages')).not.toContainText('OTHER_MERCHANT_SENTINEL');
});

test('ordinary chat refresh reads persisted corrections once without replaying a task', async ({page}) => {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  const result=await page.evaluate(async()=>{
    _authUser={id:'restore-owner'};_authToken='synthetic';_authVerifiedOwnerId='restore-owner';
    localStorage.setItem('noteai_chat_session',JSON.stringify({ownerUserId:'restore-owner',sessionId:'original-session',noteId:'old-note',noteTitle:'旧标题',noteBody:'旧缓存',score:75,version:1,savedAt:Date.now()}));
    const calls=[];
    window.fetch=async(url,init)=>{calls.push({url:String(url),method:init?.method||'GET'});return new Response(JSON.stringify({type:'chat_state',session_id:'original-session',note_id:'new-note',title:'已保存更正',body:'最新说明1杯',version:2,current_score:71,grade:'良好',fact_update_pending:true,confirmed_facts:[{question_id:'drink',question:'套餐含几杯？',merchant:'自测店',object:'双人套餐',time_range:'9月',answer:'1杯，仅周末',status:'confirmed'}]}),{status:200});};
    await chatRestoreSession();return {calls,session:_chatSessionId,note:_chatParentNoteId};
  });
  expect(result.calls).toHaveLength(1);expect(result.calls[0].method).toBe('GET');
  expect(result.calls[0].url).toContain('/chat/tasks/original-session');
  expect(result.session).toBe('original-session');expect(result.note).toBe('new-note');
  await expect(page.locator('#chat-note-scroll')).toContainText('最新说明1杯');
  await expect(page.locator('#chat-messages')).toContainText('更正前的历史版本');
  await page.evaluate(()=>showPage('chat'));
  await page.getByRole('button',{name:'查看或纠正本次商家确认',exact:true}).click();
  await expect(page.getByPlaceholder('填写更正后的完整说明')).toHaveValue('1杯，仅周末');
});

for(const outcome of ['failed','changed-session','changed-owner']) {
  test(`chat restore ${outcome} does not replay or attach corrections to another context`,async({page})=>{
    await page.goto('/NoteAI_Pro_Demo_Framer.html');
    const result=await page.evaluate(async(mode)=>{
      _authUser={id:'restore-owner'};_authToken='synthetic';_authVerifiedOwnerId='restore-owner';
      localStorage.setItem('noteai_chat_session',JSON.stringify({ownerUserId:'restore-owner',sessionId:'original-session',noteTitle:'原缓存',noteBody:'旧正文',score:75,version:1,savedAt:Date.now()}));
      const calls=[];
      window.fetch=async(url,init)=>{calls.push(init?.method||'GET');
        if(mode==='changed-session')_chatSessionId='another-session';
        if(mode==='changed-owner'){_authUser={id:'other-owner'};_authToken='other';}
        return new Response(JSON.stringify({type:'chat_state',note_id:'wrong-note',title:'LATE_PRIVATE',body:'LATE_PRIVATE',confirmed_facts:[{question_id:'drink',question:'LATE_PRIVATE',answer:'PRIVATE'}]}),{status:mode==='failed'?503:200});};
      await chatRestoreSession();return {calls,session:_chatSessionId};
    },outcome);
    expect(result.calls).toEqual(['GET']);
    await expect(page.locator('#chat-messages')).not.toContainText('LATE_PRIVATE');
    await expect(page.locator('#chat-note-scroll')).not.toContainText('LATE_PRIVATE');
    if(outcome==='failed') {
      await expect(page.locator('#chat-messages')).toContainText('不会重新生成或扣分');
      await expect(page.locator('#chat-send-btn')).toBeDisabled();
    }
  });
}
