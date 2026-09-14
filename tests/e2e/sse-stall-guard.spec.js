const { test, expect } = require('./offline-fixture');

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
    _authToken = 'synthetic-stream-owner-token';
    _authUser = {id: 'stream-test-owner', username: 'marked-stream-test'};
    _authVerifiedOwnerId = 'stream-test-owner';
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
        connectDelayMs: 800,
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
      __installSseMock('/generate/stream', {chunks: [], closeDelayMs: 800});
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

async function openClarification(page, operation = 'generate') {
  await openApp(page);
  await page.evaluate(operation => {
    _authToken='synthetic-owner-token'; _authUser={id:'merchant-a',username:'marked-test'};
    _authVerifiedOwnerId='merchant-a';
    window.__clarifyCounts={resume:0,save:0,read:0};
    window.__clarifyState={type:'clarification_required',status:'waiting_for_input',version:1,
      session_id:'a1111111-1111-4111-8111-111111111111',operation,domain:'美食',questions:[
        {question_id:'package',field:'package_inclusions',question:'198元的双人套餐包含门票吗？',merchant:'蓝猫店',object:'双人套餐',time_range:'9月',required:true,options:['包含','不包含']},
        {question_id:'drink',field:'drink_option',question:'套餐饮品需要写进这篇笔记吗？',merchant:'蓝猫店',object:'双人套餐',required:false,options:[]}
      ],answers:[],completed_steps:['素材理解','专家分析']};
    window.__clarifyMode='success';
    const fallback=window.fetch.bind(window);
    window.fetch=async (url,opts={})=>{
      const path=String(url);
      if (path.includes('/chat/tasks')) {
        __clarifyCounts.read++;
        return Response.json(path.endsWith('/chat/tasks')?{tasks:[__clarifyState]}:__clarifyState);
      }
      if (path.endsWith('/chat/message')) {
        __clarifyCounts.resume++;
        window.__clarifySubmission=JSON.parse(opts.body);
        if (__clarifyMode==='reject') return Response.json({detail:'请完整填写回答'}, {status:422});
        if (__clarifyMode==='disconnect') throw new Error('synthetic disconnect');
        __clarifyState={...__clarifyState,status:'completed',version:2,result:{type:'complete',note_title:'蓝猫店双人套餐',note_body:'双人套餐198元，门票另购。',ces_percentile:76,grade:'良好',saved_note_id:'b1111111-1111-4111-8111-111111111111',saved_note_version:1,pending_confirmation:[],title_variants:[],expert_opinions:[]}};
        const response='data: '+JSON.stringify({type:'clarification_acknowledged',message:'已更新：套餐不含门票，饮品不写。继续原素材。'})+'\n\n'+'data: '+JSON.stringify(__clarifyState.result)+'\n\n';
        return new Response(response,{headers:{'Content-Type':'text/event-stream'}});
      }
      if (opts.method==='POST' && path.endsWith('/notes')) {__clarifyCounts.save++;throw Error('Must not save twice');}
      return fallback(url,opts);
    };
    showTaskClarification(__clarifyState);
  }, operation);
}

test.describe('original task clarification', () => {
  test('free answer and per-question omit resume same task without uploads or second save', async ({page}) => {
    await openClarification(page);
    const long='仅9月周末有效，不含门票。'+ '赠饮不另外销售，饮品本次不写。'.repeat(18);
    await page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true}).fill(long);
    await page.getByRole('combobox',{name:'套餐饮品需要写进这篇笔记吗？处理方式'}).selectOption('omitted');
    await page.getByRole('button',{name:'按这些说明继续',exact:true}).dblclick();
    await expect.poll(()=>page.evaluate(()=>__clarifyCounts.resume)).toBe(1);
    await expect(page.locator('#genMainTitle')).toHaveText('蓝猫店双人套餐');
    const submitted=await page.evaluate(()=>__clarifySubmission);
    expect(submitted.task_answers[0].answer).toBe(long);
    expect(submitted.task_answers[1].status).toBe('omitted');
    expect(submitted.session_id).toBe('a1111111-1111-4111-8111-111111111111');
    expect(submitted).not.toHaveProperty('image_base64');
    expect(await page.evaluate(()=>__clarifyCounts.save)).toBe(0);
  });

  test('waiting is terminal transport but never a successful product result', async ({page}) => {
    await openClarification(page,'analyze');
    const result=await page.evaluate(async()=>{
      const stream=await consumeJsonSse(new Response('data: '+JSON.stringify(__clarifyState)+'\n\n'),{terminalTypes:['complete','error','clarification_required'],onEvent:()=>{}});
      return {outcome:stream.outcome,complete:completeProductResult({_waiting_for_input:true}),resume:__clarifyCounts.resume};
    });
    expect(result).toEqual({outcome:'awaiting_input',complete:false,resume:0});
    await expect(page.locator('[data-task-clarification]')).toContainText('原素材无需重传');
    await expect(page.locator('#diagnoseSubmitBtn')).not.toHaveAttribute('aria-busy','true');
  });

  test('unknown submission never retries; original readback determines whether editing is possible', async ({page}) => {
    await openClarification(page);
    await page.evaluate(()=>{__clarifyMode='disconnect';});
    await page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true}).fill('不包含');
    await page.getByRole('combobox',{name:'套餐饮品需要写进这篇笔记吗？处理方式'}).selectOption('unknown');
    await page.getByRole('button',{name:'按这些说明继续',exact:true}).click();
    await expect(page.locator('[data-task-message]')).toContainText('连接中断');
    await expect(page.getByRole('button',{name:'按这些说明继续',exact:true})).toBeDisabled();
    expect(await page.evaluate(()=>__clarifyCounts.resume)).toBe(1);
    await page.getByRole('button',{name:'核实原任务状态',exact:true}).click();
    await expect(page.getByRole('button',{name:'按这些说明继续',exact:true})).toBeEnabled();
    await expect(page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true})).toHaveValue('不包含');
    expect(await page.evaluate(()=>__clarifyCounts.resume)).toBe(1);
  });

  test('explicit rejection keeps free answer editable and account switch removes private questions', async ({page}) => {
    await openClarification(page);
    await page.evaluate(()=>{__clarifyMode='reject';});
    await page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true}).fill('不包含');
    await page.getByRole('combobox',{name:'套餐饮品需要写进这篇笔记吗？处理方式'}).selectOption('omitted');
    await page.getByRole('button',{name:'按这些说明继续',exact:true}).click();
    await expect(page.getByRole('button',{name:'按这些说明继续',exact:true})).toBeEnabled();
    await page.evaluate(()=>{chatClearUserState();_authUser={id:'merchant-b'};_authToken='different';});
    await expect(page.locator('[data-task-clarification]')).toHaveCount(0);
    expect(await page.evaluate(()=>__clarifyCounts.resume)).toBe(1);
    expect(await page.evaluate(()=>localStorage.getItem(taskReferenceKey('merchant-b')))).toBeNull();
  });

  test('verified account restores from server; saved locator contains no answer or material', async ({page}) => {
    await openClarification(page);
    const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem(taskReferenceKey('merchant-a'))));
    expect(Object.keys(saved).sort()).toEqual(['operation','session_id']);
    await page.evaluate(()=>{document.querySelector('[data-task-clarification]').remove();showPage('upload');return restorePendingTaskClarification();});
    await page.getByRole('button',{name:'有一篇笔记等你补充，继续原任务'}).click();
    await expect(page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true})).toBeVisible();
    expect(await page.evaluate(()=>__clarifyCounts.resume)).toBe(0);
  });
});

test('merchant correction opens existing dialogue editor with the complete prior answer', async ({page}) => {
  await openApp(page);
  await page.evaluate(()=>{
    _authToken='synthetic-token';_authUser={id:'merchant-a'};_chatSessionId='same-dialogue';
    showPage('chat');document.getElementById('chat-no-session').style.display='none';document.getElementById('chat-active-area').style.display='flex';
    chatAppendConfirmedFacts([{question_id:'q1',field:'package_inclusions',question:'双人套餐包含什么？',merchant:'蓝猫店',object:'双人套餐',time_range:'9月周末',answer:'包含门票，仅9月周末有效。'}]);
    window.__correction=[];chatSendMessage=async options=>{__correction.push(options);return 'success';};
  });
  await page.getByRole('button',{name:'查看或纠正本次商家确认'}).click();
  const editor=page.locator('[data-supplement-field="confirmation_q1"]');
  await expect(editor).toHaveValue('包含门票，仅9月周末有效。');
  await editor.fill('更正：不包含门票，仅9月周末有效，平日不适用。');
  await page.getByRole('button',{name:'提交补充并优化'}).click();
  expect(await page.evaluate(()=>__correction.length)).toBe(1);
  expect(await page.evaluate(()=>__correction[0].supplement_values.confirmation_q1)).toBe('更正：不包含门票，仅9月周末有效，平日不适用。');
  expect(await page.evaluate(()=>__correction[0].useCurrentAttachments)).toBe(false);
});
