const { test, expect } = require('./offline-fixture');

async function installReportHistory(page) {
  await openApp(page);
  await page.evaluate(() => {
    const created='2026-09-15T22:00:00Z';
    const generation={note_title:'已保存的德厨报告',note_body:'历史生成正文，不是后续改写。 #真实素材',
      ces_percentile:73,grade:'良好',_domain:'美食',saved_note_id:'saved-generation',saved_note_version:1,
      created_at:created,title_variants:['历史备选标题'],cover_analysis:'历史素材观察',
      expert_opinions:[{role:'内容创作师',opinion:'历史专家分析原文'}],
      fact_enrichment:{provider:'amap',status:'no_matching_facts',facts:{},sources:[],calls:{http_requests:1}}};
    const diagnosis={diagnosis_id:'saved-diagnosis',note_title:'旧诊断报告',ai_diagnosis:'原诊断意见',
      desc:'原诊断素材',ces_percentile:61,composite_score:61,grade:'良好',domain:'美食',created_at:created,
      suggested_titles:['方案甲'],suggested_plans:[{title:'方案甲',body:'原诊断方案正文'}],expert_opinions:[],features:{}};
    window.__reportFixtures={generation,diagnosis};
    window.__reportRequests=[];
    const nativeFetch=window.fetch.bind(window);
    window.fetch=async(url,opts={})=>{
      const path=new URL(String(url),location.href).pathname;
      if(!path.includes('/reports')) return nativeFetch(url,opts);
      __reportRequests.push({path,method:opts.method || 'GET'});
      if(path.endsWith('/reports')) return Response.json({total:2,reports:[
        {report_type:'generate',report_id:'generation-task',note_title:generation.note_title,domain:'美食',ces_percentile:73,created_at:created},
        {report_type:'analyze',report_id:'saved-diagnosis',note_title:diagnosis.note_title,domain:'美食',ces_percentile:61,created_at:created}]});
      if(path.endsWith('/reports/generate/generation-task')) {
        if(window.__delayReport) await new Promise(resolve=>{window.__releaseReport=resolve;});
        return Response.json({report_type:window.__wrongReportType ? 'analyze' : 'generate',report_id:'generation-task',result:generation});
      }
      if(path.endsWith('/reports/analyze/saved-diagnosis')) return Response.json({report_type:'analyze',report_id:'saved-diagnosis',result:diagnosis});
      return Response.json({detail:'missing'},{status:404});
    };
    _generateResult={_waiting_for_input:true,session_id:'waiting-taotao'};
    _diagnoseResult=null;_diagnosePromise=null;_isGenerateMode=true;
    showTaskClarification({session_id:'waiting-taotao',operation:'generate',status:'waiting_for_input',version:1,domain:'美食',
      questions:[{question_id:'hours',question:'本分店营业时间？',merchant:'陶陶居',options:[]}],answers:[]});
    document.querySelector('[data-task-answer]').value='尚不确定，保留我的输入';
    window.__waitingPointer=localStorage.getItem(taskReferenceKey(_authUser.id));
    showPage('report');
  });
  await expect(page.locator('#gen-card-generation-task')).toBeVisible();
  // Viewing history is explicit while another task is waiting for input.
  await page.locator('#gen-card-generation-task').click();
  await expect(page.locator('#genBodyText')).toContainText('历史生成正文');
}

test('report history restores generation after refresh and keeps waiting task and diagnosis independent', async ({page}) => {
  await installReportHistory(page);
  await expect(page.getByRole('button', {name:'报告',exact:true})).toBeVisible();
  await expect(page.locator('#diag-history-list')).toContainText('生成报告');
  await expect(page.locator('#diag-history-list')).toContainText('诊断报告');
  await expect(page.locator('#genAgentResultsList')).toContainText('历史专家分析原文');
  await expect(page.locator('#detail-meta')).toContainText('2026-09-');
  await expect(page.locator('#detail-delete-btn')).toBeHidden();
  await page.locator('#diag-card-saved-diagnosis').click();
  await expect(page.locator('#detail-note-title')).toHaveText('旧诊断报告');
  await expect(page.locator('#bodyOriginal')).toHaveText('原诊断素材');
  expect(await page.evaluate(()=>reportDiagnosisResult().diagnosis_id)).toBe('saved-diagnosis');
  await page.locator('#gen-card-generation-task').click();
  await expect(page.locator('#genBodyText')).toContainText('历史生成正文');
  await expect(page.locator('#shareCardBanner')).toBeHidden();
  expect(await page.evaluate(()=>({
    task:_generateResult,diagnosis:_diagnoseResult,mode:_isGenerateMode,
    pointerUnchanged:localStorage.getItem(taskReferenceKey(_authUser.id))===__waitingPointer,
    answer:document.querySelector('[data-task-answer]').value,
    methods:[...new Set(__reportRequests.map(r=>r.method))],
  }))).toEqual({task:{_waiting_for_input:true,session_id:'waiting-taotao'},diagnosis:null,mode:true,
    pointerUnchanged:true,answer:'尚不确定，保留我的输入',methods:['GET']});
  await page.reload();
  await installReportHistory(page);
  await expect(page.locator('#genAgentResultsList')).toContainText('历史专家分析原文');
});

test('report history rejects mismatched identity and late responses after a new task or account change', async ({page}) => {
  await installReportHistory(page);
  await page.evaluate(async()=>{closeDiagDetail();__wrongReportType=true;await openReportDetail('generate','generation-task');});
  await expect(page.locator('#diag-detail-section')).toBeHidden();
  expect(await page.evaluate(()=>_historyReportSelection)).toBeNull();
  await page.evaluate(()=>{__wrongReportType=false;__delayReport=true;window.__oldRead=openReportDetail('generate','generation-task');});
  await expect.poll(()=>page.evaluate(()=>typeof __releaseReport)).toBe('function');
  await page.evaluate(async()=>{
    clearReportSelection();_generateResult={_waiting_for_input:true,session_id:'new-waiting'};
    __releaseReport();await __oldRead;
  });
  expect(await page.evaluate(()=>({selection:_historyReportSelection,task:_generateResult.session_id})))
    .toEqual({selection:null,task:'new-waiting'});
  await page.evaluate(()=>{window.__oldRead=openReportDetail('generate','generation-task');});
  await expect.poll(()=>page.evaluate(()=>typeof __releaseReport)).toBe('function');
  await page.evaluate(async()=>{chatClearUserState();_authUser={id:'other-owner'};_authToken='other-token';__releaseReport();await __oldRead;});
  expect(await page.evaluate(()=>_historyReportSelection)).toBeNull();
  await expect(page.locator('#diag-history-list')).toBeEmpty();
  await expect(page.locator('#diag-detail-section')).toBeHidden();
});

async function openApp(page) {
  await page.addInitScript(() => {
    globalThis.__NOTEAI_SSE_WARNING_THRESHOLDS__ = {
      connectMs: 30,
      firstEventMs: 30,
      idleMs: 30,
      pollMs: 10,
    };
  });
  await page.route('**/synthetic-api/billing/plan', route => route.fulfill({json:{total_available_credits:11.5}}));
  await page.route('**/synthetic-api/billing/quote?*', route => route.fulfill({json:{
    operation:new URL(route.request().url()).searchParams.get('operation'),credits:8,quote_version:'synthetic-quote-v1',
    can_afford:true,monthly_credits_used:8,wallet_credits_used:0,monthly_credits_remaining:11.5,wallet_credits_balance:0,video_credits:0}}));
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

for(const operation of ['generate','analyze']) {
  test(`${operation} starts directly after server quote; double click creates one request without confirmation`,async ({page})=>{
    await openApp(page);
    let quotes=0;const submitted=[];
    await page.route('**/synthetic-api/billing/quote?*',async route=>{
      quotes++;await new Promise(resolve=>setTimeout(resolve,100));
      return route.fulfill({json:{operation,credits:8,quote_version:'direct-server-quote',can_afford:true,
        monthly_credits_used:8,wallet_credits_used:0,monthly_credits_remaining:11.5,wallet_credits_balance:0,video_credits:0}});
    });
    await page.route('**/synthetic-api/'+operation+'/stream',route=>{
      submitted.push({method:route.request().method(),id:route.request().headers()['x-request-id'],
        quoteVersion:route.request().headers()['x-billing-quote-version']});
      const result={type:'complete',note_title:'已保存的模拟直发结果',note_body:'仅本地模拟，不是生产报告。',
        saved_note_id:'synthetic-direct-saved',saved_note_version:1,ces_percentile:69,grade:'良好',plans:[],title_variants:[],expert_opinions:[]};
      return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(result)+'\n\n'});
    });
    await page.evaluate(operation=>{showPage('upload');switchMode(operation==='generate'?'generate':'diagnose');},operation);
    if(operation==='generate')await page.locator('#genBrief').fill('本地直发验证素材');
    else {
      await page.locator('.input-type',{hasText:'填写笔记／上传素材'}).click();
      await page.locator('#inputTitle').fill('本地直发标题');await page.locator('#inputDesc').fill('本地直发正文');
    }
    await page.locator(operation==='generate'?'#generateSubmitBtn':'#diagnoseSubmitBtn').dblclick();
    await expect.poll(()=>submitted.length).toBe(1);
    await expect.poll(()=>page.evaluate(operation=>operation==='generate'?_genStreamActive:_diagnosisStreamActive,operation)).toBe(false);
    expect(quotes).toBe(1);expect(submitted[0].method).toBe('POST');
    expect(submitted[0].id).toMatch(new RegExp('^'+operation+'-'));
    expect(submitted[0].quoteVersion).toBe('direct-server-quote');
    await expect(page.locator('#billing-quote-dialog')).toHaveCount(0);
    await expect(page.locator('#'+operation+'-billing-preview')).toContainText('8 积分 / 次');
    await expect(page.locator('#'+operation+'-billing-preview')).toContainText('受理时先扣周期积分');
  });

  test(`${operation} unaffordable quote keeps inputs and sends no generation request`,async ({page})=>{
    await openApp(page);
    let posts=0;const messages=[];
    page.on('dialog',dialog=>{messages.push(dialog.message());return dialog.dismiss();});
    await page.route('**/synthetic-api/billing/quote?*',route=>route.fulfill({json:{operation,credits:8,
      quote_version:'direct-insufficient-quote',can_afford:false,monthly_credits_used:0,wallet_credits_used:8,
      monthly_credits_remaining:0,wallet_credits_balance:0,video_credits:0}}));
    await page.route('**/synthetic-api/'+operation+'/stream',route=>{posts++;return route.abort();});
    await page.evaluate(operation=>{showPage('upload');switchMode(operation==='generate'?'generate':'diagnose');},operation);
    if(operation==='generate')await page.locator('#genBrief').fill('余额不足仍保留的简报');
    else {
      await page.locator('.input-type',{hasText:'填写笔记／上传素材'}).click();
      await page.locator('#inputTitle').fill('余额不足标题');await page.locator('#inputDesc').fill('余额不足仍保留的正文');
    }
    await page.locator(operation==='generate'?'#generateSubmitBtn':'#diagnoseSubmitBtn').click();
    await expect.poll(()=>messages.length).toBe(1);
    await expect.poll(()=>page.evaluate(operation=>operation==='generate'?_genStreamActive:_diagnosisStreamActive,operation)).toBe(false);
    expect(messages[0]).toContain('当前可用积分不足，本次尚未提交');expect(posts).toBe(0);
    await expect(page.locator('#billing-quote-dialog')).toHaveCount(0);
    expect(await page.evaluate(()=>Object.keys(sessionStorage).filter(key=>key.startsWith('noteai-paid-pending:')).length)).toBe(0);
    await expect(page.locator(operation==='generate'?'#genBrief':'#inputDesc')).toHaveValue(operation==='generate'?'余额不足仍保留的简报':'余额不足仍保留的正文');
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
    await page.locator('.input-type', {hasText: '填写笔记／上传素材'}).click();
    await page.locator('#inputTitle').fill('慢连接测试标题');
    await page.locator('#inputDesc').fill('慢连接测试正文');
    await page.evaluate(() => { startDiagnosis(); startDiagnosis(); });

    await expect(page.locator('[data-sse-warning="analyze"]')).toContainText('任务可能仍在处理，请不要重复提交');
    await expect(page.locator('#diagnoseSubmitBtn')).toBeDisabled();
    await expect.poll(() => page.evaluate(() => __sseRequestCounts['/analyze/stream'] || 0)).toBe(1);
    await expect.poll(() => page.evaluate(() => _diagnosisStreamActive)).toBe(false);
    await expect(page.locator('[data-sse-warning="analyze"]')).toHaveCount(0);
    await expect(page.locator('#diagnoseSubmitBtn')).toBeEnabled();
    await expect(page.locator('#nav-credits-display')).toHaveText('11.5积分');
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
    await expect.poll(() => page.evaluate(() => _generateResult?._errMsg || '')).toContain('原任务和积分');
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
    await page.locator('.input-type', {hasText: '填写笔记／上传素材'}).click();
    await page.locator('#inputTitle').fill('多字节切片标题');
    await page.locator('#inputDesc').fill('多字节切片正文');
    await page.evaluate(() => {void startDiagnosis();});

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
    await page.evaluate(() => {void startGeneration();});

    await expect.poll(() => page.evaluate(() => _generateResult?.type || '')).toBe('complete');
    await expect(page.locator('#nav-credits-display')).toHaveText('11.5积分');
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
    expect(messages[3]).toContain('积分退回');
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
        const response='data: '+JSON.stringify({type:'clarification_acknowledged',session_id:__clarifyState.session_id,version:2,operation,charged_again:false,message:'已更新：套餐不含门票，饮品不写。继续原素材。'})+'\n\n'+'data: '+JSON.stringify(__clarifyState.result)+'\n\n';
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
    await expect(page.locator('#nav-credits-display')).toHaveText('11.5积分');
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

  test('completed diagnosis keeps original result through history refresh and restores the exact input version', async ({page}) => {
    await openClarification(page,'analyze');
    await page.evaluate(()=>{
      const fallback=window.fetch.bind(window);
      const did='d1111111-1111-4111-8111-111111111111',nid='b1111111-1111-4111-8111-111111111111';
      window.__reportResult={diagnosis_id:did,saved_note_id:nid,ces_percentile:71.2,composite_score:71.2,grade:'良好',
        ai_diagnosis:'原任务的完整诊断',suggested_titles:['画面方案一','画面方案二','画面方案三'],
        suggested_plans:[1,2,3].map(i=>({title:'画面方案'+i,body:'原任务方案正文'+i,ces_percentile:73+i})),
        expert_opinions:[{role:'内容专家',opinion:'原素材的内容分析'}],weaknesses:[],features:{},pending_confirmation:[]};
      window.__historyDetailReads=0;
      window.fetch=async(url,opts={})=>{
        const path=String(url);
        if(path.includes('/reports?')) return Response.json({total:1,reports:[{report_type:'analyze',report_id:did,note_title:'原素材标题',domain:'美食',ces_percentile:71.2,created_at:'2026-09-14T08:00:00Z'}]});
        if(path.endsWith('/diagnoses/'+did) || path.endsWith('/reports/analyze/'+did)) {
          __historyDetailReads++;
          if(__historyDetailReads===3) return Response.json({detail:'temporarily unavailable'},{status:503});
          // Old diagnosis JSON is empty, but original owned note metadata exists.
          const result={diagnosis_id:did,saved_note_id:nid,note_title:'原素材标题',note_version_group:{versions:[
            {id:'different-version',body:'后续改写不能冒充原文'},{id:nid,body:'原任务上传的真实素材正文'}]}};
          return Response.json(path.includes('/reports/') ? {report_type:'analyze',report_id:did,result} : result);
        }
        return fallback(url,opts);
      };
      return finishClarifiedTask(__reportResult,__clarifyState,_chatIdentitySnapshot(),_authToken,true);
    });
    await expect(page.locator('#scoreRingNum')).toHaveText('71');
    await expect(page.locator('#bodyOriginal')).toHaveText('原任务上传的真实素材正文');
    await expect(page.locator('#bodySuggested')).toContainText('原任务方案正文');
    await expect(page.locator('#detail-meta')).not.toContainText('undefined');
    expect(await page.evaluate(()=>__historyDetailReads)).toBe(1);
    await page.locator('#diag-card-d1111111-1111-4111-8111-111111111111').click();
    await expect(page.locator('#scoreRingNum')).toHaveText('71');
    await expect(page.locator('#detail-note-title')).toHaveText('原素材标题');
    expect(await page.evaluate(()=>_diagnoseResult.suggested_plans.length)).toBe(3);
    expect(await page.evaluate(()=>_diagnoseResult.ces_percentile)).toBe(71.2);
    await page.locator('#diag-card-d1111111-1111-4111-8111-111111111111').click();
    await expect(page.locator('#detail-note-title')).toHaveText('原素材标题');
    await expect(page.locator('#scoreRingNum')).toHaveText('71');
    await expect(page.locator('#bodyOriginal')).toHaveText('原任务上传的真实素材正文');
    expect(await page.evaluate(()=>__clarifyCounts.resume)).toBe(0);
    expect(await page.evaluate(()=>__clarifyCounts.save)).toBe(0);
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

test('failed new generation preserves its inputs and never opens an older report', async ({page}) => {
  await openApp(page);
  await page.evaluate(() => {
    showPage('upload'); switchMode('generate');
    _diagnoseResult={title:'Older unrelated diagnosis',score:73,plans:[]};
    window.__oldReportLoads=0; populateReport=async()=>{__oldReportLoads++;};
    __installSseMock('/generate/stream', {chunks:[{data:'data: {"type":"error","error_code":"stream_internal_error","message":"本次处理遇到系统问题，暂未得到结果。"}\n\n'}]});
  });
  await page.locator('#genBrief').fill('Private marked restaurant test material');
  await page.locator('#generateSubmitBtn').click();
  await expect.poll(()=>page.evaluate(()=>_generateResult?._error)).toBe(true);
  await page.waitForTimeout(2200);
  expect(await page.evaluate(()=>__oldReportLoads)).toBe(0);
  await expect(page.locator('#page-report')).not.toBeVisible();
  await expect(page.locator('#genBrief')).toHaveValue('Private marked restaurant test material');
  expect(await page.evaluate(()=>__sseRequestCounts['/generate/stream'])).toBe(1);
});

test('transport heartbeats do not conceal real no-progress warnings', async ({page}) => {
  await openApp(page);
  await page.evaluate(()=>{
    window.__queueWarning=createSseWarningGuard('queue-fixture','合成任务');
    __queueWarning.connected();__queueWarning.event({type:'stage'});
    window.__queueHeartbeat=setInterval(()=>__queueWarning.event({type:'heartbeat'}),5);
  });
  await expect(page.locator('[data-sse-warning="queue-fixture"]')).toContainText('暂时没有新进度');
  await page.evaluate(()=>{
    clearInterval(__queueHeartbeat);
    __queueWarning.event({type:'queue_update',queue:{completed_calls:1}});
    __queueWarning.finish();
  });
  await expect(page.locator('[data-sse-warning="queue-fixture"]')).toHaveCount(0);
});

for(const busyCode of ['MODEL_OPERATIONS_BUSY','MODEL_USER_OPERATION_BUSY','MODEL_INPUT_CAPACITY_BUSY'])
test(`precharge overload ${busyCode} preserves inputs and clears only its unaccepted submission without retry`,async ({page})=>{
  await openApp(page);
  let submitted=0;
  await page.route('**/synthetic-api/generate/stream',route=>{
    submitted++;
    return route.fulfill({status:429,json:{detail:{code:busyCode,message:'UNTRUSTED_RAW_TEXT'}}});
  });
  await page.evaluate(()=>{showPage('upload');switchMode('generate');});
  await page.locator('#genBrief').fill('保留本次素材和说明');
  await page.locator('#generateSubmitBtn').click();
  await expect.poll(()=>page.evaluate(()=>_generateResult?._notAccepted)).toBe(true);
  expect(submitted).toBe(1);
  expect(await page.evaluate(()=>_generateResult._errMsg)).toContain('未受理、未扣积分');
  expect(await page.evaluate(()=>_generateResult._errMsg)).not.toContain('UNTRUSTED');
  expect(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('noteai-paid-pending:')).length)).toBe(0);
  await expect(page.locator('#genBrief')).toHaveValue('保留本次素材和说明');
});

for (const width of [1280,390]) test(`actual queue fields, safe cancellation and failed expert render at ${width}px`,async ({page},testInfo)=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.setViewportSize({width,height:844});
  await openApp(page);
  const calls=[];
  await page.route('**/synthetic-api/chat/tasks/11111111-1111-4111-8111-111111111111/cancel',route=>{
    calls.push(route.request().method());
    return route.fulfill({json:{cancel_requested:true,message:'已请求停止后续处理，正在等待已发请求结算；积分状态以原任务记录为准'}});
  });
  await page.evaluate(()=>{
    showPage('live');
    _handleGenStreamEvent({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true});
    _handleGenStreamEvent({type:'queue_update',queue:{active:true,state:'queued',waiting_operations:3,queued_calls:2,waiting_seconds:32,can_cancel:true,last_progress_seconds:125}});
    _handleGenStreamEvent({type:'image_progress',completed:4,total:9});
    agentDone(1,'');_handleGenStreamEvent({type:'expert_failed',agent_idx:1,role:'内容创作师',message:'该步骤未完成，正在等待结算'});
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('当前有 3 个任务等待处理');
  await expect(page.locator('#liveTaskQueue')).toContainText('本任务待处理 2 项');
  await expect(page.locator('#liveTaskQueue')).toContainText('已完成 4/9 张');
  await expect(page.locator('#liveTaskQueue')).toContainText('距上次实际处理进展 125 秒');
  await expect(page.locator('#cf1')).toHaveText('未完成');
  await expect(page.locator('#av1')).not.toHaveClass(/done/);
  const progress=await page.locator('#mainProgress').getAttribute('style');
  await page.evaluate(()=>_handleGenStreamEvent({type:'heartbeat'}));
  expect(await page.locator('#mainProgress').getAttribute('style')).toBe(progress);
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toContainText('正在等待已发请求结算');
  await expect(page.getByRole('button',{name:'取消后续处理',exact:true})).toBeDisabled();
  expect(calls).toEqual(['POST']);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#liveTaskQueue').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath(`queue-${width}.png`)});
  expect(errors).toEqual([]);
});

test('queue remount retains original task and cancellation uses the JSON boundary contract',async ({page})=>{
  await openApp(page);
  const requests=[];
  await page.route('**/synthetic-api/chat/tasks/*/cancel',route=>{
    requests.push({method:route.request().method(),contentType:route.request().headers()['content-type'],body:route.request().postData()});
    return route.fulfill({json:{message:'原任务已接收取消，已发请求正在结算',cancel_requested:true}});
  });
  await page.evaluate(()=>{
    showPage('live');
    _handleGenStreamEvent({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true});
    _handleGenStreamEvent({type:'queue_update',queue:{state:'queued',can_cancel:true,waiting_operations:3}});
    showPage('upload');showPage('live');
    _handleGenStreamEvent({type:'queue_update',queue:{state:'running',can_cancel:true}});
  });
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-task-id','11111111-1111-4111-8111-111111111111');
  await expect(page.getByRole('button',{name:'取消后续处理',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toContainText('原任务已接收取消');
  expect(requests).toEqual([{method:'POST',contentType:'application/json',body:'{}'}]);
  await page.evaluate(()=>{
    _handleGenStreamEvent({type:'queue_update',queue:{state:'idle',can_cancel:false}});
    document.querySelector('[data-live-cancel]').click();
  });
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  expect(requests.length).toBe(1);
});

test('late cancellation and stale terminal cannot overwrite completed queue status',async ({page})=>{
  await openApp(page);
  let release;let cancelCount=0;
  await page.route('**/synthetic-api/chat/tasks/*/cancel',async route=>{
    cancelCount++;
    if(cancelCount===1)await new Promise(resolve=>{release=resolve;});
    await route.fulfill({json:{message:'迟到的取消答复',cancel_requested:true}});
  });
  await page.evaluate(()=>{
    showPage('live');
    _handleGenStreamEvent({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true});
    _handleGenStreamEvent({type:'queue_update',queue:{state:'running',can_cancel:true}});
    renderLiveQueueEvent({type:'complete'},()=>false);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('正在处理请求');
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect.poll(()=>typeof release).toBe('function');
  await page.evaluate(()=>renderLiveQueueEvent({type:'complete'}));
  release();
  await page.waitForTimeout(100);
  await expect(page.locator('#liveTaskQueue')).toContainText('处理已完成');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  await page.evaluate(()=>{document.querySelector('[data-live-cancel]').click();showPage('upload');showPage('live');});
  await expect(page.locator('#liveTaskQueue')).toContainText('处理已完成');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  // Analyze uses the same explicit identity guard before terminal rendering.
  await page.evaluate(()=>_handleAnalyzeStreamEvent({type:'error'},()=>false));
  await expect(page.locator('#liveTaskQueue')).toContainText('处理已完成');
  await page.evaluate(()=>{
    _handleGenStreamEvent({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true});
    _handleGenStreamEvent({type:'queue_update',queue:{state:'running',can_cancel:true}});
  });
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toContainText('迟到的取消答复');
  expect(cancelCount).toBe(2);
});

for(const operation of ['generate','analyze']) test(`late ${operation} overload JSON cannot replace a newer task`,async ({page})=>{
  await openApp(page);
  await page.evaluate(operation=>{
    showPage('upload');switchMode(operation==='generate'?'generate':'diagnose');
    const nativeFetch=window.fetch.bind(window);
    window.fetch=async(url,options)=>{
      if(!String(url).includes('/'+operation+'/stream'))return nativeFetch(url,options);
      return {status:429,clone:()=>({json:()=>new Promise(resolve=>{window.__releaseBusyJson=resolve;})})};
    };
  },operation);
  if(operation==='generate'){
    await page.locator('#genBrief').fill('旧请求保留说明');
    await page.locator('#generateSubmitBtn').click();
  } else {
    await page.locator('.input-type',{hasText:'填写笔记／上传素材'}).click();
    await page.locator('#inputTitle').fill('旧请求标题');
    await page.locator('#inputDesc').fill('旧请求正文');
    await page.evaluate(()=>{startDiagnosis();});
  }
  await expect.poll(()=>page.evaluate(()=>typeof __releaseBusyJson)).toBe('function');
  await page.evaluate(operation=>{
    if(operation==='generate') {_activeGeneratePaidRequestId='new-task';_generateResult={newTask:true};_genStreamActive=true;}
    else {_activeAnalyzePaidRequestId='new-task';_diagnoseResult={newTask:true};_diagnosisStreamActive=true;}
    __releaseBusyJson({detail:{code:'MODEL_OPERATIONS_BUSY'}});
  },operation);
  await page.waitForTimeout(100);
  expect(await page.evaluate(operation=>operation==='generate'?_generateResult:_diagnoseResult,operation)).toEqual({newTask:true});
  expect(await page.evaluate(operation=>operation==='generate'?_genStreamActive:_diagnosisStreamActive,operation)).toBe(true);
  expect(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('noteai-paid-pending:')).length)).toBe(1);
});

test('rejected cross-entry analyze cannot erase running generate task or its cancel target',async ({page})=>{
  await openApp(page);
  const cancelled=[];
  await page.route('**/synthetic-api/chat/tasks/*/cancel',route=>{
    cancelled.push(new URL(route.request().url()).pathname);
    return route.fulfill({json:{message:'正在等待原生成结算',cancel_requested:true}});
  });
  await page.evaluate(()=>{
    const nativeFetch=window.fetch.bind(window);
    window.fetch=async(url,options)=>{
      if(String(url).includes('/generate/stream')){
        const encoder=new TextEncoder();
        return new Response(new ReadableStream({start(controller){
          window.__crossGenerateController=controller;
          window.__crossGenerateEmit=event=>controller.enqueue(encoder.encode('data: '+JSON.stringify(event)+'\n\n'));
          __crossGenerateEmit({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true});
          __crossGenerateEmit({type:'queue_update',queue:{state:'running',can_cancel:true}});
        }}),{status:200,headers:{'Content-Type':'text/event-stream'}});
      }
      if(String(url).includes('/analyze/stream'))return Response.json({detail:{code:'MODEL_USER_OPERATION_BUSY'}},{status:429});
      return nativeFetch(url,options);
    };
    showPage('upload');switchMode('generate');
  });
  await page.locator('#genBrief').fill('原生成任务素材');
  await page.locator('#generateSubmitBtn').click();
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-task-id','11111111-1111-4111-8111-111111111111');
  await expect(page.locator('#page-live')).toBeVisible();
  await page.evaluate(()=>{showPage('upload');switchMode('diagnose');});
  await page.locator('.input-type',{hasText:'填写笔记／上传素材'}).click();
  await page.locator('#inputTitle').fill('另一入口未受理的诊断');await page.locator('#inputDesc').fill('不替换原生成');
  await page.evaluate(()=>{startDiagnosis();});
  await expect.poll(()=>page.evaluate(()=>_diagnoseResult?._notAccepted)).toBe(true);
  await page.evaluate(()=>{
    showPage('live');
    __crossGenerateEmit({type:'queue_update',queue:{state:'queued',can_cancel:true,waiting_operations:2}});
  });
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-task-id','11111111-1111-4111-8111-111111111111');
  await expect(page.locator('#liveTaskQueue')).toContainText('当前有 2 个任务等待处理');
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toContainText('正在等待原生成结算');
  expect(cancelled).toEqual(['/synthetic-api/chat/tasks/11111111-1111-4111-8111-111111111111/cancel']);
});

test('old cross-entry stream cannot update or terminate a newly authoritative task',async ({page})=>{
  await openApp(page);
  await page.evaluate(()=>{
    showPage('live');
    window.__streamA=()=>true;window.__streamB=()=>true;
    _handleGenStreamEvent({type:'task_created',task_id:'11111111-1111-4111-8111-111111111111',can_cancel:true},__streamA);
    _handleAnalyzeStreamEvent({type:'task_created',task_id:'22222222-2222-4222-8222-222222222222',can_cancel:true},__streamB);
    _handleAnalyzeStreamEvent({type:'queue_update',queue:{state:'running',can_cancel:true}},__streamB);
    _handleGenStreamEvent({type:'queue_update',queue:{state:'settling',can_cancel:false}},__streamA);
    _handleGenStreamEvent({type:'complete'},__streamA);
    _handleGenStreamEvent({type:'stage',progress:99,label:'旧A不应覆盖'},__streamA);
  });
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-task-id','22222222-2222-4222-8222-222222222222');
  await expect(page.locator('#liveTaskQueue')).toContainText('正在处理请求');
  await expect(page.getByRole('button',{name:'取消后续处理',exact:true})).toBeVisible();
  await expect(page.locator('#liveTaskQueue')).not.toContainText('处理已完成');
  expect(await page.evaluate(()=>_liveQueueState.terminal)).toBe(false);
  await page.evaluate(()=>{
    window.__resumedB=()=>true;
    _handleAnalyzeStreamEvent({type:'task_created',task_id:'22222222-2222-4222-8222-222222222222',can_cancel:true},__resumedB);
    _handleAnalyzeStreamEvent({type:'queue_update',queue:{state:'queued',can_cancel:true,queued_calls:3}},__resumedB);
    _handleAnalyzeStreamEvent({type:'complete'},__streamB);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('本任务待处理 3 项');
  expect(await page.evaluate(()=>_liveQueueState.terminal)).toBe(false);
});

// Synthetic owner-task responses exercise the actual public HTML and DOM only.
// They are not provider calls, real refunds or production task-state evidence.
const readbackTaskId='2b80b30c-5acf-48ee-bb16-13e0cfc8bd09';
function readbackTask(status='failed', active=false, refunded=false) {
  return {task_id:readbackTaskId,session_id:readbackTaskId,operation:'generate',status,
    can_cancel:status==='running',refund_status:refunded?'refunded':'pending',
    billing:{status:refunded?'refunded':'charged',credits_used:refunded?0:8,refunded_credits:refunded?8:0},
    ...(typeof active==='boolean'?{queue:{active,state:active?'settling':'idle'}}:{})};
}
async function openReadbackIncident(page) {
  await openApp(page);
  await page.evaluate(async taskId=>{
    window.__readbackSubmission=await paidSubmissionIdentity('generate',{brief:'marked-nine-image-readback'},
      {quote_version:'synthetic-readback-quote'});
    _activeGeneratePaidRequestId=__readbackSubmission.requestId;
    bindPaidSubmissionReceipt(__readbackSubmission,{request_id:taskId});
    const identity=_chatIdentitySnapshot(),token=_authToken;
    window.__readbackGuard=()=>_chatIdentityMatches(identity) && _authToken===token
      && _activeGeneratePaidRequestId===__readbackSubmission.requestId;
    showPage('live');
    _handleGenStreamEvent({type:'task_created',task_id:taskId,can_cancel:true},__readbackGuard);
    _handleGenStreamEvent({type:'image_progress',completed:3,total:9},__readbackGuard);
    _handleGenStreamEvent({type:'queue_update',queue:{active:true,state:'running',can_cancel:true}},__readbackGuard);
  },readbackTaskId);
}

test('owner GET closes the stale 3/9 card without inventing a refund; manual reread confirms refund',async ({page},testInfo)=>{
  await page.setViewportSize({width:390,height:844});
  await openReadbackIncident(page);
  let snapshot=readbackTask('failed',true),reads=0;
  const methods=[];
  await page.route('**/synthetic-api/chat/tasks/'+readbackTaskId,route=>{
    reads++;methods.push(route.request().method());return route.fulfill({json:snapshot});
  });
  await page.evaluate(async()=>{
    const identity=_chatIdentitySnapshot(),token=_authToken,queue=_liveQueueState;
    const task=await readPaidTaskState(__readbackSubmission,'generate',token);
    displayPaidTaskState(task,__readbackSubmission,'generate',identity,token,queue);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('本轮处理已结束');
  await expect(page.locator('#liveTaskQueue')).toContainText('已完成 3/9 张');
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-queue-active','true');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  await expect(page.locator('#generation-paid-task-status')).toContainText('正在核对本次积分退回');
  await expect(page.locator('#generation-paid-task-status')).not.toContainText('已按原来源退回');
  await page.evaluate(()=>{
    _handleGenStreamEvent({type:'task_created',task_id:__readbackSubmission.serverRequestId,can_cancel:true},__readbackGuard);
    _handleGenStreamEvent({type:'image_progress',completed:4,total:9},__readbackGuard);
    _handleGenStreamEvent({type:'stage',stage:'p2',progress:42,label:'旧事件不应恢复专家运行'},__readbackGuard);
    _handleGenStreamEvent({type:'error',billing:{status:'refunded'}},__readbackGuard);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('已完成 3/9 张');
  await expect(page.locator('#generation-paid-task-status')).toContainText('正在核对本次积分退回');
  expect(await page.evaluate(()=>_generateResult.billing.status)).toBe('charged');
  snapshot=readbackTask('failed',false,true);
  await page.getByRole('button',{name:'重新核实原任务',exact:true}).click();
  await expect(page.locator('#generation-paid-task-status')).toContainText('本次积分已按原来源退回');
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-queue-active','false');
  await expect(page.locator('#liveTaskQueue')).toContainText('当前没有活动处理');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  expect(reads).toBe(2);expect(methods).toEqual(['GET','GET']);
  expect(await page.evaluate(()=>currentPaidSubmission(__readbackSubmission))).toBe(false);
  await page.locator('#generation-paid-task-status').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('390-authoritative-refund-readback.png')});
});

test('finite twelve-read watcher stops automatically and manual reread sends only one GET',async ({page})=>{
  await openReadbackIncident(page);
  await page.clock.install();
  let reads=0,snapshot=readbackTask('outcome_unknown',null);
  await page.route('**/synthetic-api/chat/tasks/'+readbackTaskId,route=>{
    reads++;return route.fulfill({json:snapshot});
  });
  await page.evaluate(()=>{window.__readbackWatch=watchPaidTask(__readbackSubmission,'generate',_chatIdentitySnapshot(),_authToken);});
  await expect.poll(()=>reads).toBe(1);
  for(let attempt=2;attempt<=12;attempt++) {
    await page.clock.fastForward(5000);
    await expect.poll(()=>reads).toBe(attempt);
  }
  await expect(page.locator('[data-paid-task-polling-stopped]')).toContainText('已停止自动核对');
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-queue-active','unrecorded');
  await expect(page.locator('#liveTaskQueue')).toContainText('活动状态未记录');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  expect(await page.evaluate(()=>({_unknown:_generateResult._outcome_unknown,failed:_generateResult._error || false})))
    .toEqual({_unknown:true,failed:false});
  await page.clock.fastForward(60000);expect(reads).toBe(12);
  snapshot=readbackTask('running',true);
  await page.getByRole('button',{name:'重新核实原任务',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-queue-active','true');
  await expect(page.locator('[data-live-cancel]')).toBeVisible();
  await expect(page.locator('[data-paid-task-polling-stopped]')).toContainText('已停止自动核对');
  expect(reads).toBe(13);
  await page.clock.fastForward(60000);expect(reads).toBe(13);
  snapshot=readbackTask('failed',false,true);
  await page.getByRole('button',{name:'重新核实原任务',exact:true}).click();
  await expect(page.locator('#generation-paid-task-status')).toContainText('本次积分已按原来源退回');
  expect(reads).toBe(14);
  await page.clock.fastForward(60000);expect(reads).toBe(14);
});

test('same-task waiting and completed snapshots hide cancellation and retain real queue status',async ({page})=>{
  await openReadbackIncident(page);
  await page.evaluate(()=>{
    const task={task_id:__readbackSubmission.serverRequestId,session_id:__readbackSubmission.serverRequestId,
      operation:'generate',status:'waiting_for_input',can_cancel:false,queue:{active:false}};
    displayPaidTaskState(task,__readbackSubmission,'generate',_chatIdentitySnapshot(),_authToken);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('原任务等待补充信息');
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  await page.evaluate(()=>{
    const task={task_id:__readbackSubmission.serverRequestId,session_id:__readbackSubmission.serverRequestId,
      operation:'generate',status:'completed',can_cancel:false,queue:{active:false},
      report_ref:{report_type:'generate',report_id:'saved-original'}};
    displayPaidTaskState(task,__readbackSubmission,'generate',_chatIdentitySnapshot(),_authToken);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('处理已完成');
  await expect(page.getByRole('button',{name:'查看本次已保存报告',exact:true})).toBeVisible();
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-queue-active','false');
  await page.evaluate(()=>{
    _handleGenStreamEvent({type:'stage',stage:'p4',progress:90,label:'迟到旧流'},__readbackGuard);
    _handleGenStreamEvent({type:'error',task_status:'outcome_unknown'},__readbackGuard);
  });
  await expect(page.locator('#liveTaskQueue')).toContainText('处理已完成');
  await expect(page.locator('#generation-paid-task-status')).toContainText('生成已完成，原报告已保存');
});

async function openUsageTaskRecord(page) {
  await openApp(page);
  await page.route('**/synthetic-api/billing/usage?*',route=>route.fulfill({json:{
    window:{kind:'calendar_month',timezone:'UTC',basis:'usage_record_started_at'},accounting:{},by_operation:{},
    recent_records:[{request_id:readbackTaskId,operation:'generate',label:'爆文生成',source:'subscription',
      credits_used:8,monthly_credits_used:8,wallet_credits_used:0,recorded_at:'2026-10-17T14:20:44Z'}]}}));
  await page.getByRole('button',{name:'成长档案',exact:true}).click();
  await expect(page.locator('[data-usage-task-read]')).toHaveCount(1);
  await page.locator('#profile-usage-toggle').click();
}

test('recent usage provides cross-device owner-only GET state without local submission or generated result',async ({page},testInfo)=>{
  await page.setViewportSize({width:1280,height:844});
  await openUsageTaskRecord(page);
  const methods=[];
  await page.route('**/synthetic-api/chat/tasks/'+readbackTaskId,route=>{
    methods.push(route.request().method());return route.fulfill({json:readbackTask('failed',false)});
  });
  await page.getByRole('button',{name:'查看任务状态',exact:true}).click();
  const panel=page.locator('[data-usage-task-state]');
  await expect(panel).toHaveAttribute('data-task-id',readbackTaskId);
  await expect(panel).toHaveAttribute('data-queue-active','false');
  await expect(panel).toContainText('当前没有活动处理');
  await expect(panel).toContainText('正在核对本次积分退回');
  expect(methods).toEqual(['GET']);
  expect(await page.evaluate(()=>({pending:pendingPaidSubmissions('generate').length,
    active:_activeGeneratePaidRequestId,result:_generateResult}))).toEqual({pending:0,active:null,result:null});
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('1280-recent-usage-task-state.png')});
});

test('late usage GET cannot terminate a newer task or show another account data',async ({page})=>{
  await openUsageTaskRecord(page);
  let release;
  await page.route('**/synthetic-api/chat/tasks/'+readbackTaskId,async route=>{
    await new Promise(resolve=>{release=resolve;});return route.fulfill({json:readbackTask('failed',false,true)});
  });
  await page.getByRole('button',{name:'查看任务状态',exact:true}).click();
  await expect.poll(()=>typeof release).toBe('function');
  await page.evaluate(()=>{
    window.__newReadbackGuard=()=>true;
    _activeGeneratePaidRequestId='new-generation';
    _generateResult={newTask:true};
    _handleGenStreamEvent({type:'task_created',task_id:'22222222-2222-4222-8222-222222222222',can_cancel:true},__newReadbackGuard);
    _handleGenStreamEvent({type:'queue_update',queue:{active:true,state:'running',can_cancel:true}},__newReadbackGuard);
  });
  release();
  await expect(page.locator('[data-usage-task-state]')).toHaveAttribute('data-queue-active','false');
  expect(await page.evaluate(()=>({task:_liveQueueState.taskId,terminal:_liveQueueState.terminal,result:_generateResult})))
    .toEqual({task:'22222222-2222-4222-8222-222222222222',terminal:false,result:{newTask:true}});
  release=undefined;
  await page.getByRole('button',{name:'查看任务状态',exact:true}).click();
  await expect.poll(()=>typeof release).toBe('function');
  await page.evaluate(()=>{chatClearUserState();_authUser={id:'other-owner'};_authToken='other-owner-token';});
  release();
  await expect(page.locator('[data-usage-task-read]')).toHaveCount(0);
  await expect(page.locator('#profile-usage-recent')).not.toContainText(readbackTaskId);
  expect(await page.evaluate(()=>_liveQueueState)).toBeNull();
});

function actualBackendResumeEvents(operation) {
  // Exercise the real a11 resume/event/timing wrappers with isolated business
  // dependencies. No supplier, DB mutation, authentication shortcut or payment.
  const {execFileSync}=require('node:child_process');
  const path=require('node:path');
  const fs=require('node:fs');
  const localPython=path.resolve(__dirname,'../../.venv/bin/python');
  const python=process.env.NOTEAI_TEST_PYTHON || (fs.existsSync(localPython)?localPython:'python3');
  const script=String.raw`
import os,sys,asyncio,json
from pathlib import Path
from contextlib import ExitStack
from unittest import mock
from types import SimpleNamespace
os.environ['PYTHON_DOTENV_DISABLED']='1'
sys.path.insert(0,str(Path.cwd()/'model'))
import api
operation=sys.argv[1];sid='a1111111-1111-4111-8111-111111111111'
claim={'state':'owner','user_id':'merchant-a','request_id':sid,'operation':operation,'key_hash':'mock-original-hash','charge':{'usage_id':'mock-original-usage'}}
prepared={'pipeline':'generate_stream' if operation=='generate' else 'analyze','domain':'美食','brief':'原素材','timing':None,'cover_feats':{},'visual_score':None,'local_time':'','user_tier':'free','memory_context':'','metadata':{},'agent_context':'原观察','source_material':'原素材','image_desc':'原图片观察','request':{'note_title':'原始标题','desc':'原始正文','domain':'美食'}}
task={'version':2,'prepared':prepared,'answers':[{'question_id':'package','answer':'不包含门票','status':'confirmed','revision':2}]}
complete={'type':'complete','note_title':'蓝猫店原任务完成','note_body':'根据本次说明继续原素材。','ces_percentile':73.2,'grade':'良好','suggested_plans':[],'expert_opinions':[],'pending_confirmation':[]}
async def generate(**kwargs):
 yield {'type':'stage','stage':'p3','label':'继续原任务仲裁','progress':60}
 await asyncio.sleep(.02)
 yield {'type':'expert_opinion','agent_idx':4,'role':'仲裁专家','content':'原说明已用于本次内容','detail':'','progress':70}
 yield dict(complete)
async def analyze(*args,emit,**kwargs):
 await emit({'type':'stage','stage':'arbitrate','label':'继续原任务诊断','progress':60})
 await asyncio.sleep(.02)
 await emit({'type':'expert_opinion','agent_idx':4,'role':'仲裁专家','content':'原说明已用于诊断','detail':'','progress':70})
 return SimpleNamespace(model_dump=lambda:dict(complete))
async def run():
 req=api.ChatMessageInput(session_id=sid,task_version=1,task_answers=[{'question_id':'package','status':'confirmed','answer':'不包含门票'}],message='按本次说明继续')
 response=await api._resume_clarified_task(req,{'id':'merchant-a'})
 return [json.loads(chunk[6:]) async for chunk in response.body_iterator]
with ExitStack() as stack:
 for target,name,value in [(api._clarification,'resume',(claim,task)),(api._clarification,'answer_context','本次补充：不包含门票'),(api._clarification,'pending_confirmation',[]),(api._billing,'activate_usage',None),(api._billing,'get_charge_receipt',{'request_id':sid,'status':'completed'}),(api._clarification,'save_result',None),(api._idempotency,'mark_completed',True),(api._idempotency,'mark_failed_and_refund',True),(api._public_product,'bind_task_claim',None),(api._public_product,'assert_result_known',None),(api._public_product,'queue_status',{'active':True,'state':'running','can_cancel':True,'completed_calls':1})]:
  stack.enter_context(mock.patch.object(target,name,return_value=value))
 stack.enter_context(mock.patch.object(api,'_SSE_HEARTBEAT_SECONDS',.002))
 stack.enter_context(mock.patch.object(api,'_generate_pipeline_stream',side_effect=generate))
 stack.enter_context(mock.patch.object(api,'_run_analyze_pipeline',side_effect=analyze))
 events=asyncio.run(run())
assert events[0]['type']=='clarification_acknowledged' and events[0]['session_id']==sid and events[0]['version']==2 and events[0]['charged_again'] is False
assert not any(e['type']=='task_created' for e in events)
assert events[-1]['type']=='complete' and any(e['type']=='queue_update' for e in events)
print(json.dumps(events,ensure_ascii=False))
`;
  return JSON.parse(execFileSync(python,['-c',script,operation],
    {cwd:path.resolve(__dirname,'../..'),encoding:'utf8',timeout:15000}));
}

for(const operation of ['generate','analyze']) test(`actual backend ${operation} clarification acknowledgement resumes queue and closes on terminal`,async ({page})=>{
  const events=actualBackendResumeEvents(operation);
  await openClarification(page,operation);
  await page.evaluate(({events,operation})=>{
    window.__resumeSequence=events;window.__resumeCancelPaths=[];
    const fallback=window.fetch.bind(window);
    window.fetch=async(url,opts={})=>{
      if(String(url).endsWith('/cancel')){
        __resumeCancelPaths.push(String(url));return Response.json({cancel_requested:true,message:'原接续已请求停止后续，等待结算'});
      }
      if(!String(url).endsWith('/chat/message'))return fallback(url,opts);
      const encoder=new TextEncoder();
      return new Response(new ReadableStream({start(controller){
        for(const event of events.slice(0,-1))controller.enqueue(encoder.encode('data: '+JSON.stringify(event)+'\n\n'));
        window.__finishActualResume=()=>{controller.enqueue(encoder.encode('data: '+JSON.stringify(events.at(-1))+'\n\n'));controller.close();};
      }}),{headers:{'Content-Type':'text/event-stream'}});
    };
    const handler=operation==='generate'?_handleGenStreamEvent:_handleAnalyzeStreamEvent;
    handler({type:'task_created',task_id:__clarifyState.session_id,can_cancel:false});
    handler({type:'clarification_required'});
  },{events,operation});
  await page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true}).fill('不包含门票');
  await page.getByRole('combobox',{name:'套餐饮品需要写进这篇笔记吗？处理方式'}).selectOption('omitted');
  await page.getByRole('button',{name:'按这些说明继续',exact:true}).click();
  await expect(page.locator('#liveTaskQueue')).toHaveAttribute('data-task-id','a1111111-1111-4111-8111-111111111111');
  await expect(page.locator('#cf4')).toHaveText('已完成');
  expect(await page.evaluate(()=>_liveQueueState.terminal)).toBe(false);
  await expect(page.getByRole('button',{name:'取消后续处理',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'取消后续处理',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>__resumeCancelPaths.length)).toBe(1);
  expect(await page.evaluate(()=>__resumeCancelPaths[0])).toContain('/chat/tasks/a1111111-1111-4111-8111-111111111111/cancel');
  await page.evaluate(()=>__finishActualResume());
  await expect.poll(()=>page.evaluate(()=>_liveQueueState.terminal)).toBe(true);
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  expect(events.some(e=>e.type==='task_created')).toBe(false);
});

for(const invalid of ['session','version']) test(`mismatched clarification ${invalid} cannot take over or complete original task`,async ({page})=>{
  const events=actualBackendResumeEvents('generate');
  if(invalid==='session')events[0].session_id='ffffffff-ffff-4fff-8fff-ffffffffffff';else events[0].version=99;
  await openClarification(page);
  await page.evaluate(events=>{
    const fallback=window.fetch.bind(window);
    window.fetch=async(url,opts={})=>String(url).endsWith('/chat/message')
      ?new Response(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join(''),{headers:{'Content-Type':'text/event-stream'}})
      :fallback(url,opts);
    _handleGenStreamEvent({type:'task_created',task_id:__clarifyState.session_id,can_cancel:false});
    _handleGenStreamEvent({type:'clarification_required'});
  },events);
  await page.getByRole('textbox',{name:'198元的双人套餐包含门票吗？',exact:true}).fill('不包含门票');
  await page.getByRole('combobox',{name:'套餐饮品需要写进这篇笔记吗？处理方式'}).selectOption('omitted');
  await page.getByRole('button',{name:'按这些说明继续',exact:true}).click();
  await expect(page.locator('[data-task-message]')).toContainText('尚未匹配原任务');
  expect(await page.evaluate(()=>_generateResult?._outcome_unknown)).toBe(true);
  expect(await page.evaluate(()=>_liveQueueState.terminal)).toBe(true);
  await expect(page.locator('[data-live-cancel]')).toBeHidden();
  await expect(page.locator('#genMainTitle')).not.toHaveText('蓝猫店原任务完成');
});
