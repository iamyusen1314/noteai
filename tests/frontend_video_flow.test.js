// Pure VM checks of production functions; no browser, credentials or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const html = fs.readFileSync(require('node:path').join(__dirname, '../NoteAI_Pro_Demo_Framer.html'), 'utf8');
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script); // Detect duplicate declarations and malformed production JS.
function source(name) {
  const match = new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(script);
  assert.ok(match, name);
  for (let end = script.indexOf('}', match.index); end >= 0; end = script.indexOf('}', end+1)) {
    const value = script.slice(match.index, end+1);
    try { new vm.Script(value); return value; } catch {}
  }
  throw Error('Incomplete function '+name);
}
function context(extra={}) {
  const c = vm.createContext({console, Promise, ...extra});
  c.load = (...names) => names.forEach(n=>vm.runInContext(source(n), c));
  return c;
}
test('normal combined note submits all original fields once during image persistence', async()=>{
  let release, requests=[];
  const stored = new Promise(r=>release=r);
  const values={inputTitle:'测试标题',inputDesc:'测试正文 #测试',inputDomain:'旅行',noteMediaType:'video'};
  const c=context({
    PUBLIC_PRODUCT:true, API_BASE:'', _authToken:'synthetic', _authUser:{id:'owner'},
    _diagnosisPreparing:false,_diagnosisStreamActive:false,_diagVideoState:'ready',
    _diagVideoFileId:'video-original',_diagVideoAttempt:1,_coverBase64:'data:image/png;base64,cover',_diagImages:[],
    document:{getElementById:id=>({value:values[id]}),querySelector:()=>({textContent:'填写笔记／上传素材'})},
    requirePublicCapability:()=>true,requireProductConsent:()=>true,
    _chatIdentitySnapshot:()=>({ownerId:'owner'}),_chatIdentityMatches:()=>true,
    getConstraintTags:()=>['不改标题','不改封面'],getContentIntentPayload:()=>({content_intent:'种草'}),
    authHeader:()=>({Authorization:'Bearer synthetic'}),shouldAskMerchantBeforeRun:()=>false,
    privateImageInput:async()=>{await stored;return 'cover-original';},
    updateDiagnosisSubmitState(){},showToast(){},formatLocalTimeWithConstraints:()=> '2026091510',
    createSseWarningGuard:()=>({connected(){},finish(){}}),createPaidRequestId:()=> 'single-test',
    fetch:async(_url,options)=>{requests.push(JSON.parse(options.body));return {status:401};},
    openAuthModal(){},setTimeout(){},
  });
  c.load('diagnosisUsesVideo','startDiagnosis','prepareDiagnosis');
  const first=c.startDiagnosis(); await Promise.resolve(); await c.startDiagnosis();
  assert.equal(requests.length,0);release();await first;await c._diagnosePromise;
  assert.equal(requests.length,1);
  assert.equal(requests[0].video_file_id,'video-original');
  assert.equal(requests[0].cover_image,'cover-original');
  assert.equal(requests[0].note_title,'测试标题');assert.equal(requests[0].desc,'测试正文 #测试');
  assert.equal(requests[0].domain,'旅行');assert.equal(requests[0].input_mode,'video');
  assert.deepEqual(requests[0].user_constraints,['不改标题','不改封面']);
});
for (const kind of ['Diag','Gen']) {
  test(kind+' video does not upload or publish a late result across account changes',async()=>{
    for (const phase of ['metadata','response']) {
      let video, release, calls=0;
      const response = new Promise(r=>release=r);
      const c=context({PUBLIC_PRODUCT:true,_authToken:'first',_diagVideoAttempt:0,_genVideoAttempt:0,
        _chatIdentitySnapshot:()=>({token:'first'}),requirePublicCapability:()=>true,
        URL:{createObjectURL:()=> 'local',revokeObjectURL(){}},FormData:class {append(){}},
        document:{getElementById:()=>({style:{}}),createElement:()=>{video={duration:57};return video;}},
        _setDiagVideoState(s){c.diagState=s;},_setGenVideoState(s){c.genState=s;},
        fetch:async()=>{calls++;return response;},API_BASE:'',showToast(){},openAuthModal(){},
      });
      c._chatIdentityMatches=id=>id.token===c._authToken;
      const name=kind==='Diag'?'_uploadDiagVideoFile':'_uploadVideoFile';c.load(name);
      const running=c[name]({name:'synthetic.mp4',size:10});
      if(phase==='metadata')c._authToken='second';
      video.onloadedmetadata();await new Promise(resolve=>setImmediate(resolve));
      if(phase==='response'){assert.equal(calls,1);c._authToken='second';release({ok:true,json:async()=>({file_id:'wrong-owner'})});}
      await running;
      assert.equal(calls,phase==='metadata'?0:1);
      assert.notEqual(c.diagState,'ready');assert.notEqual(c.genState,'done');
    }
  });
}
test('partial score remains unavailable; full score and escaped originals work',()=>{
  const c=context();c.load('_numOrNull','diagnosisDisplayScore','formatScoreValue','escapeHtml');
  assert.equal(c.diagnosisDisplayScore({composite_score:74,input_diagnostics:{score_scope:'partial_input'}}),null);
  assert.equal(c.formatScoreValue(null),'–');assert.equal(c.diagnosisDisplayScore({composite_score:74}),74);
  assert.equal(c.escapeHtml('<img src=x>'),'&lt;img src=x&gt;');
});

test('diagnosis chat keeps complete video and independent cover observations',()=>{
  const c=context();c.load('diagnosisMediaContext');
  const value=c.diagnosisMediaContext({video_analysis:'v'.repeat(2000)+'VIDEO_END_SENTINEL',cover_analysis:'c'.repeat(2000)+'COVER_END_SENTINEL'});
  assert.ok(value.includes('【视频音画观察】'));assert.ok(value.includes('VIDEO_END_SENTINEL'));
  assert.ok(value.includes('【用户独立封面观察】'));assert.ok(value.endsWith('COVER_END_SENTINEL'));
  assert.ok(source('startChatFromDiagnosis').includes('cover_analysis:   diagnosisMediaContext(_diagnoseResult)'));
});

test('new generation clears old diagnosis title and destructive target',()=>{
  const elements={'detail-note-title':{textContent:'旧诊断'},'detail-meta':{textContent:'综合 48.1'},
    'detail-delete-btn':{onclick:()=>{throw Error('old deletion');},style:{display:'block'}}};
  const c=context({_currentDiagId:'old-diagnosis',document:{getElementById:id=>elements[id]}});
  c.load('renderGenerationHeader');
  c.renderGenerationHeader({note_title:'本次生成标题',_domain:'旅行',ces_percentile:73});
  assert.equal(c._currentDiagId,null);assert.equal(elements['detail-note-title'].textContent,'本次生成标题');
  assert.ok(elements['detail-meta'].textContent.includes('73.0'));
  assert.equal(elements['detail-delete-btn'].onclick,null);assert.equal(elements['detail-delete-btn'].style.display,'none');
  c.renderGenerationHeader(null);assert.equal(elements['detail-note-title'].textContent,'本次生成');
  assert.ok(!elements['detail-meta'].textContent.includes('73'));
});

test('server-saved generation receipt never posts a duplicate note',async()=>{
  const c=context({_authToken:'test',_chatIdentityMatches:()=>true,
    fetch:async()=>{throw Error('duplicate note save');}});
  c.load('autoSaveGeneratedNote');
  const result={saved_note_id:'original-server-note',saved_note_version:1};
  await c.autoSaveGeneratedNote(result,{},'test');
  await c.autoSaveGeneratedNote(result,{},'test');
  assert.equal(result._save_status,'saved');assert.equal(result._saved_note_id,'original-server-note');
});

test('generation uses only its visible constraints and explicit time choice',()=>{
  const selections={
    'section-diagnose':['不改标题','不改封面','固定发布时间 18:00','目标：带货'],
    'section-generate':[],
  };
  const c=context({document:{getElementById:id=>({querySelectorAll:()=>selections[id].map(textContent=>({textContent}))})},
    formatLocalTime:()=> '2026091512'});
  c.load('getConstraintTags','formatLocalTimeWithConstraints');
  assert.deepEqual(Array.from(c.getConstraintTags('generate')),[]);
  assert.equal(c.formatLocalTimeWithConstraints(c.getConstraintTags('generate')),'2026091512');
  selections['section-generate']=['重点优化：互动率','固定发布时间 18:00'];
  assert.deepEqual(Array.from(c.getConstraintTags('generate')),selections['section-generate']);
  assert.equal(c.formatLocalTimeWithConstraints(c.getConstraintTags('generate')),'2026091518');
  assert.deepEqual(Array.from(c.getConstraintTags()),selections['section-diagnose']);
  assert.ok(source('startGeneration').includes("getConstraintTags('generate')"));
});

test('saved empty constraints survive chat entry and session recovery without hidden form state',async()=>{
  for (const constraints of [[],undefined]) {
    const requests=[];
    const note={_saved_note_id:'owned-note',note_title:'原标题',note_body:'原正文',_domain:'旅行',user_constraints:constraints};
    const c=context({_generateResult:note,_authToken:'test',_chatParentNoteId:'owned-note',API_AUTH:'',
      completeProductResult:()=>true,chatBeginNoteContext:()=>true,_chatConversationSnapshot:()=>({}),
      _chatConversationMatches:()=>true,_numOrNull:Number,localStorage:{removeItem(){}},
      document:{getElementById:()=>({style:{},focus(){}})},showPage(){},authHeader:()=>({}),
      getContentIntentPayload:()=>({}),formatLocalTimeWithConstraints:()=> '2026091512',
      getConstraintTags:()=>{throw Error('hidden diagnosis state read');},
      fetch:async(_url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>({session_id:'same-owned-session'})};},
      chatUpdateNote(){},chatUpdateLearn(){},chatAppendAi(){},chatAppendSupplementPrompts(){},
      chatAppendConfirmedFacts(){},chatSaveSessionToStorage(){},showToast:msg=>{throw Error(msg);},
    });
    c.load('startChatOptimization','_recreateChatSession');
    await c.startChatOptimization();assert.equal(await c._recreateChatSession(),true);
    assert.equal(requests.length,2);
    for (const req of requests) {assert.deepEqual(req.generate_context.user_constraints,[]);assert.equal(req.user_constraints,null);}
  }
});

test('duplicate screenshot selections preserve one recognition and completed aggregate',async()=>{
  let calls=0, invalidations=0;
  const c=context({_ssFileSelectionRevision:0,_ssOcrRevision:1,_ssImages:[],_ssOcrCache:new Map(),
    FileReader:class{readAsDataURL(f){this.onload({target:{result:f.bytes}});}},
    showToast(){},_setSsImageStatus(){},_renderSsThumbs(){},_updateScreenshotOcrUi(){},
    _invalidateSsAggregateState(){invalidations++;c._screenshotExtracted=null;},
    _ocrImages:async imgs=>{calls+=imgs.length;imgs.forEach(i=>c._ssOcrCache.set(i.dataURL,{ocr_request_id:'one'}));c._screenshotExtracted={body:'保留的结果'};},
  });
  c.load('_addSsFiles');
  const f={type:'image/png',name:'test.png',bytes:'same-content'};
  await c._addSsFiles([f,{...f,name:'another-name.png'}]); await c._ssOcrPromise;
  assert.equal(c._ssImages.length,1); assert.equal(calls,1);
  const saved=c._screenshotExtracted;
  await c._addSsFiles([f]);
  assert.equal(c._ssImages.length,1); assert.equal(calls,1); assert.equal(invalidations,1);
  assert.equal(c._screenshotExtracted,saved);
});

test('screenshot aggregation retains long text and separates photo observations',()=>{
  const elements={};
  const c=context({_ssOcrRevision:1,_ssImages:[],_ssOcrCache:new Map(),_ssOcrErrors:new Map(),
    document:{getElementById:id=>(elements[id] ||= {style:{}})},
    _ssImageSnapshot:()=>[],_isCurrentSsBatch:()=>true,
    _getScreenshotRecognitionState:()=>({total:c._ssImages.length,ok:c._ssImages.length,pending:0,failed:0}),
    _applyScreenshotDomain(){},_renderScreenshotImageSummaries(){},updateDiagnosisSubmitState(){},showToast(){},
    _supportedScreenshotDomain:d=>d,
  });
  c.load('screenshotOriginalBody','_normalizeSsTags','_splitSsBodyAndTags','_bodyCharCountWithoutSsTags','_mergeAndShowOcrResults');
  const set=values=>{c._ssImages=values.map((_,i)=>({dataURL:String(i)}));c._ssOcrCache=new Map(values.map((v,i)=>[String(i),v]));};
  set([{type:'C',body:'甲乙',domain:'旅行'},{type:'A',title:'原文',body:'甲乙丙丁',domain:'旅行'},
    {type:'C',body:'末尾独有信息',domain:'旅行'},{type:'B',cover_desc:'画面是绿树',domain:'旅行'}]);
  c._mergeAndShowOcrResults();
  assert.equal(c._screenshotExtracted.text_body,'甲乙丙丁\n\n末尾独有信息');
  assert.ok(c._screenshotExtracted.body.includes('画面是绿树'));
  set([{type:'B',cover_desc:'画面是绿树',domain:'旅行'},{type:'B',cover_desc:'画面是房间',domain:'旅行'}]);
  c._mergeAndShowOcrResults();
  assert.equal(c._screenshotExtracted.text_body,'');assert.equal(c._screenshotExtracted._charCount,0);
  assert.equal(c._screenshotExtracted.is_photo_only,true);
  assert.ok(c._screenshotExtracted.body.includes('画面是绿树'));assert.ok(c._screenshotExtracted.body.includes('画面是房间'));
  const legacy={type:'A',title:'原标题',body:'原正文\n\n【配图视觉描述】绿树与房间',cover_desc:'绿树与房间',domain:'旅行'};
  const untouched=JSON.stringify(legacy);set([legacy]);c._mergeAndShowOcrResults();
  assert.equal(c._screenshotExtracted.text_body,'原正文');assert.equal(c._screenshotExtracted._charCount,3);
  assert.equal(JSON.stringify(legacy),untouched); // Original recovery hash remains valid.
  assert.equal(c.screenshotOriginalBody({...legacy,body:'正文中引用【配图视觉描述】绿树与房间，然后接续原文'}),'正文中引用【配图视觉描述】绿树与房间，然后接续原文');
});

test('photo-only screenshot diagnosis submits empty original prose and real media',async()=>{
  let payload;
  const c=context({PUBLIC_PRODUCT:true,API_BASE:'',_authToken:'synthetic',_authUser:{id:'owner'},
    _diagnosisPreparing:false,_diagnosisStreamActive:false,_diagVideoState:'idle',_diagVideoAttempt:0,
    _screenshotExtracted:{title:'',body:'【图1视觉观察】房间',text_body:'',tags:'',is_photo_only:true,_charCount:0},
    _ssImages:[{mediaRef:'original-image',dataURL:'not-used'}],_ssOcrPromise:null,
    document:{getElementById:()=>({value:'旅行'}),querySelector:()=>({textContent:'截图上传'})},
    requirePublicCapability:()=>true,requireProductConsent:()=>true,
    _chatIdentitySnapshot:()=>({ownerId:'owner'}),_chatIdentityMatches:()=>true,
    getConstraintTags:()=>[],getContentIntentPayload:()=>({}),authHeader:()=>({}),
    _getScreenshotRecognitionState:()=>({total:1,ok:1,failed:0,pending:0}),
    shouldAskMerchantBeforeRun:()=>false,privateImageInput:async x=>x,
    updateDiagnosisSubmitState(){},showToast(){},formatLocalTimeWithConstraints:()=> '20260915',
    createSseWarningGuard:()=>({connected(){},finish(){}}),createPaidRequestId:()=> 'photo-test',
    fetch:async(url,options)=>{payload=JSON.parse(options.body);return {status:401};},
    openAuthModal(){},setTimeout(){},
  });
  c.load('screenshotOriginalBody','_normalizeSsTags','_joinSsBodyAndTags','diagnosisUsesVideo','startDiagnosis','prepareDiagnosis');
  await c.startDiagnosis();await c._diagnosePromise;
  assert.equal(payload.note_title,'');assert.equal(payload.desc,'');
  assert.equal(payload.ocr_char_count,0);
  assert.equal(payload.cover_image,'original-image');assert.equal(payload.domain,'旅行');
});


test('reselected recovered screenshot matches normalized owner ref without new OCR identity',async()=>{
  let ocr=0, uploads=0;
  const original={dataURL:'stored-ref',mediaRef:'stored-ref',ocrRequestId:'original-paid-id',recovered:true};
  const result={type:'A',body:'原文',model_used:'original-model'};
  const c=context({_ssFileSelectionRevision:0,_ssOcrRevision:1,_ssImages:[original],_ssOcrCache:new Map([['stored-ref',result]]),
    _screenshotExtracted:{body:'原文'},FileReader:class{readAsDataURL(f){this.onload({target:{result:f.bytes}});}},
    _chatIdentitySnapshot:()=>({id:'owner'}),_chatIdentityMatches:()=>true,showToast(){},
    privateImageInput:async(value,refs)=>{uploads++;assert.deepEqual([...refs],['stored-ref']);return 'stored-ref';},
    _ocrImages:()=>{ocr++;},_invalidateSsAggregateState:()=>{throw Error('original result invalidated');},
  });c.load('_addSsFiles');await c._addSsFiles([{type:'image/png',name:'renamed.png',bytes:'raw-png'}]);
  assert.equal(uploads,1);assert.equal(ocr,0);assert.equal(c._ssImages.length,1);
  assert.equal(c._ssImages[0],original);assert.equal(c._ssOcrCache.get('stored-ref'),result);
  assert.equal(original.ocrRequestId,'original-paid-id');
});
