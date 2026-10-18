const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
const html=fs.readFileSync(require('node:path').join(__dirname,'../NoteAI_Pro_Demo_Framer.html'),'utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script);
function source(name){const match=new RegExp('^(?:async )?function '+name+'\\(','m').exec(script);assert.ok(match,name);for(let end=script.indexOf('}',match.index);end>=0;end=script.indexOf('}',end+1)){const code=script.slice(match.index,end+1);try{new vm.Script(code);return code;}catch{}}throw Error(name);}
function make(extra={}){
 const storage=new Map(),elements=new Map();
 class Element{constructor(tag){this.tagName=tag;this.style={};this.children=[];this.textContent='';}append(...children){this.children.push(...children);for(const e of children)if(e.id)elements.set(e.id,e);}addEventListener(event,fn){this[event]=fn;}showModal(){}close(){}remove(){}replaceChildren(){this.children=[];}}
 const body=new Element('body');const c=vm.createContext({console,window:{},crypto:crypto.webcrypto,TextEncoder,Uint8Array,_authUser:{id:'owner-a'},_authToken:'synthetic-a',_billingQuoteBusy:false,_genVideoFileId:'same-video',_genVideoExpiresAt:Date.now()+86400000,API_AUTH:'https://offline.invalid',API_BASE:'https://offline.invalid',authHeader:()=>({Authorization:'Bearer synthetic'}),showToast(){},openAuthModal(){},showQuotaExceededModal(){},openCreditRecords(){},_chatIdentitySnapshot:()=>({ownerId:'owner-a'}),_chatIdentityMatches:()=>true,readPaidTaskState:async()=>({status:'outcome_unknown',operation:'analyze',task_id:'original-task'}),displayPaidTaskState(){},watchPaidTask(){},sessionStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),body},...extra});
 c.load=(...names)=>names.forEach(name=>vm.runInContext(source(name),c));c.load('paidTaskFundsResolved','createPaidRequestId','paidSubmissionIdentity','currentPaidSubmission','finishPaidSubmission','confirmBillingQuote','pendingPaidSubmissions','generationVideoExpiryMessage','generationVideoSubmissionMessage','showGenerationVideoSubmissionMessage','preparePaidSubmission','bindPaidSubmissionReceipt','finishPendingTaskReceipt','restoreWaitingPaidSubmission');return {c,storage,elements,Element};
}
const quote={operation:'analyze',credits:6,video_credits:0,monthly_credits_used:4,wallet_credits_used:2,can_afford:true,quote_version:'server-six'};
test('unknown retry retains original key, quote version and exact body across hour change; no media stored',async()=>{
 const {c,storage}=make();let calls=0;c.createPaidRequestId=()=>`analyze-${++calls}`;
 const original={note_title:'private title',cover_image:'private-media-ref',local_time:'2026091710'};
 const a=await c.paidSubmissionIdentity('analyze',original,quote);
 const retry={...original,local_time:'2026091711'};
 const b=await c.paidSubmissionIdentity('analyze',retry,{...quote,quote_version:'changed'});
 assert.equal(a.requestId,b.requestId);assert.equal(b.quoteVersion,'server-six');assert.deepEqual(retry,original);assert.equal(calls,1);
 assert.ok(![...storage.values()].join().includes('private title'));assert.ok(![...storage.values()].join().includes('private-media-ref'));
 c.finishPaidSubmission(b);const next=await c.paidSubmissionIdentity('analyze',original,quote);assert.notEqual(next.requestId,a.requestId);
});
test('pending identity is isolated by account and material payload',async()=>{
 const {c}=make();let n=0;c.createPaidRequestId=()=>`id-${++n}`;
 const a=await c.paidSubmissionIdentity('analyze',{video_file_id:'video-a'},quote);
 const changed=await c.paidSubmissionIdentity('analyze',{video_file_id:'video-b'},quote);assert.notEqual(a.requestId,changed.requestId);
 c._authUser={id:'owner-b'};c._authToken='synthetic-b';const b=await c.paidSubmissionIdentity('analyze',{video_file_id:'video-a'},quote);assert.notEqual(a.requestId,b.requestId);
});
test('server quote returns directly without a second confirmation and keeps actual charge disclosure',async()=>{
 let request;const {c,elements,Element}=make({fetch:async(url,options)=>{request={url,options};return {ok:true,json:async()=>quote};}});
 const preview=new Element('div');elements.set('analyze-billing-preview',preview);
 const accepted=await c.confirmBillingQuote('analyze',true);
 assert.match(request.url,/has_video=true/);assert.equal(request.options.body,undefined);
 assert.equal(elements.has('billing-quote-confirm'),false);assert.equal(elements.has('billing-quote-dialog'),false);
 assert.match(preview.textContent,/6 积分 \/ 次/);assert.match(preview.textContent,/受理时先扣周期积分/);
 assert.equal(accepted.quote_version,'server-six');assert.equal(c._billingQuoteBusy,false);
});
test('quote unavailable or unaffordable never confirms a paid submission',async()=>{
 for(const kind of ['offline','insufficient','malformed']){
  let quotaCalls=0;const {c}=make({showQuotaExceededModal:()=>quotaCalls++,fetch:async()=>{if(kind==='offline')throw Error('offline');return {ok:true,json:async()=>kind==='malformed'?{credits:6}:{...quote,can_afford:false}};}});
  assert.equal(await c.confirmBillingQuote('analyze',true),null);assert.equal(quotaCalls,kind==='insufficient'?1:0);
 }
});
test('quote account switch cannot show or accept prior account pricing',async()=>{
 let release;const {c,elements}=make({fetch:()=>new Promise(resolve=>release=resolve)});
 const pending=c.confirmBillingQuote('generate',true);c._authUser={id:'owner-b'};c._authToken='synthetic-b';release({ok:true,json:async()=>quote});assert.equal(await pending,null);assert.equal(elements.has('billing-quote-confirm'),false);
});
test('receipt displays actual server debit and monthly/wallet split',()=>{
 const {c,elements,Element}=make();const el=new Element('div');elements.set('report-billing-receipt',el);c.load('renderBillingReceipt');
 c.renderBillingReceipt({credits_used:6,monthly_credits_used:4,wallet_credits_used:2,status:'charged'});assert.match(el.children[0].textContent,/实际扣分 6 积分 · 周期 4 \+ 充值 2/);
 c.renderBillingReceipt(null);assert.equal(el.style.display,'none');
});
test('only proven refund or explicit reservation release clears pending stream errors; ambiguous errors retain identity',()=>{
 for(const name of ['startGeneration','prepareDiagnosis']){
  const code=source(name);assert.match(code,/paidTaskFundsResolved\(terminal\)\) finishPaidSubmission/);assert.match(code,/'X-Billing-Quote-Version': submission.quoteVersion/);assert.match(code,/preparePaidSubmission\(/);
 }
});


test('same pending identity reads the original task and never dispatches or quotes another paid request',async()=>{
 let quoted=0,read=0,watched=0;const {c,storage}=make({readPaidTaskState:async()=>{read++;return {status:'outcome_unknown',operation:'analyze',task_id:'original-task'};},watchPaidTask:()=>{watched++;},fetch:async()=>{quoted++;throw Error('new quote must not be requested');}});
 const original={video_file_id:'same-video',local_time:'2026091710'};
 const pending=await c.paidSubmissionIdentity('analyze',original,quote);
 const retry={...original,local_time:'2026091711'};
 const restored=await c.preparePaidSubmission('analyze',retry);
 assert.equal(restored,null);assert.deepEqual(retry,original);assert.equal(quoted,0);assert.equal(read,1);assert.equal(watched,1);assert.equal(storage.has(pending.storageKey),true);
});
test('a distinct user intent uses its own quote and request identity while the old task stays retained',async()=>{
 const {c,storage}=make();let quoted=0;c.confirmBillingQuote=async()=>{quoted++;return quote;};
 await c.paidSubmissionIdentity('analyze',{video_file_id:'original'},quote);
 const next=await c.preparePaidSubmission('analyze',{video_file_id:'new-upload-ref'});
 assert.ok(next?.requestId);assert.equal(quoted,1);assert.equal(storage.size,2);
});
test('a confirmed refunded failure permits one explicit new quoted submission',async()=>{
 const {c,storage}=make({readPaidTaskState:async()=>({status:'failed',task_id:'original-task',billing:{status:'refunded'}})});
 const original=await c.paidSubmissionIdentity('generate',{video_file_id:'same-video'},quote);
 c.displayPaidTaskState=(_task,submission)=>c.finishPaidSubmission(submission);
 c.confirmBillingQuote=async()=>quote;
 const next=await c.preparePaidSubmission('generate',{video_file_id:'same-video'});
 assert.ok(next?.requestId);assert.notEqual(next.requestId,original.requestId);
 assert.equal(storage.has(original.storageKey),true);
 assert.equal(storage.size,1);
});
test('expired video checks original settled task before refusing a fresh quote or POST',async()=>{
 let originalReads=0,quoted=0,notice='';
 const {c,storage}=make({_genVideoExpiresAt:Date.now()-86400000,
   readPaidTaskState:async()=>{originalReads++;return {status:'failed',task_id:'original-task',refund_status:'refunded',billing:{status:'refunded'}};},
   showToast:message=>{notice=message;}});
 const original=await c.paidSubmissionIdentity('generate',{video_file_id:'same-video'},quote);
 c.displayPaidTaskState=(_task,submission)=>c.finishPaidSubmission(submission);
 c.confirmBillingQuote=async()=>{quoted++;return quote;};
 const fresh=await c.preparePaidSubmission('generate',{video_file_id:'same-video'});
 assert.equal(fresh,null);assert.equal(originalReads,1);assert.equal(quoted,0);
 assert.match(notice,/暂存已到期或即将到期.*重新上传/);
 assert.equal(storage.has(original.storageKey),false);
});
test('video about to expire is blocked before any quote; a sufficiently live upload proceeds',async()=>{
 let quoted=0;const {c}=make();c.confirmBillingQuote=async()=>{quoted++;return quote;};
 c._genVideoExpiresAt=Date.now()+2*60*1000;
 assert.equal(await c.preparePaidSubmission('generate',{video_file_id:'same-video'}),null);assert.equal(quoted,0);
 c._genVideoExpiresAt=Date.now()+20*60*1000;
 assert.ok((await c.preparePaidSubmission('generate',{video_file_id:'same-video'}))?.requestId);assert.equal(quoted,1);
});
test('video expiry while the quote dialog is open still prevents a paid identity',async()=>{
 const {c,storage}=make({_genVideoExpiresAt:Date.now()+20*60*1000});
 c.confirmBillingQuote=async()=>{c._genVideoExpiresAt=Date.now()+2*60*1000;return quote;};
 assert.equal(await c.preparePaidSubmission('generate',{video_file_id:'same-video'}),null);
 assert.equal(storage.size,0);
});
test('original task lookup is authenticated, read only and bound to its paid request ID',async()=>{
 let request;const {c}=make({fetch:async(url,options)=>{request={url,options};return {ok:true,json:async()=>({tasks:[{task_id:'task-1',operation:'generate',status:'failed',billing:{status:'refunded'}}]})};}});
 c.load('readPaidTaskState');
 const submission=await c.paidSubmissionIdentity('generate',{video_file_id:'video'},quote);
 const task=await c.readPaidTaskState(submission,'generate','synthetic-a');
 assert.equal(task.task_id,'task-1');assert.match(request.url,/chat\/tasks\?operation=generate$/);
 assert.equal(request.options.method,undefined);assert.equal(request.options.headers['X-Request-ID'],submission.requestId);
 assert.equal(request.options.headers.Authorization,'Bearer synthetic-a');
});
test('bounded task watcher keeps a pending charge until the server confirms refund',async()=>{
 const {c,storage}=make();
 const submission=await c.paidSubmissionIdentity('generate',{video_file_id:'video'},quote);
 const states=[
   {status:'outcome_unknown',refund_status:'not_requested'},
   {status:'failed',refund_status:'pending',billing:{status:'charged'}},
   {status:'failed',refund_status:'refunded',billing:{status:'refunded'}},
 ];
 let reads=0;c.PAID_TASK_READ_ATTEMPTS=3;c.PAID_TASK_READ_INTERVAL_MS=0;c._paidTaskWatchers=new Map();
 c.setTimeout=resolve=>resolve();
 c.readPaidTaskState=async()=>{reads++;return states.shift();};
 c.displayPaidTaskState=(task,paid)=>{
   const confirmed=task.status==='failed' && task.refund_status==='refunded';
   if(confirmed)c.finishPaidSubmission(paid);
   return confirmed;
 };
 c.load('watchPaidTask');
 const task=await c.watchPaidTask(submission,'generate',{ownerId:'owner-a'},'synthetic-a');
 assert.equal(reads,3);assert.equal(task.refund_status,'refunded');assert.equal(storage.has(submission.storageKey),false);
 assert.equal(c._paidTaskWatchers.size,0);
});
test('unresolved task watcher stops after its read limit and retains the paid identity',async()=>{
 const {c,storage}=make();
 const submission=await c.paidSubmissionIdentity('generate',{video_file_id:'video'},quote);
 let reads=0;c.PAID_TASK_READ_ATTEMPTS=2;c.PAID_TASK_READ_INTERVAL_MS=0;c._paidTaskWatchers=new Map();
 c.setTimeout=resolve=>resolve();
 c.readPaidTaskState=async()=>{reads++;return {status:'failed',refund_status:'pending',billing:{status:'charged'}};};
 c.displayPaidTaskState=()=>false;
 c.load('watchPaidTask');
 assert.equal(await c.watchPaidTask(submission,'generate',{ownerId:'owner-a'},'synthetic-a'),null);
 assert.equal(reads,2);assert.equal(storage.has(submission.storageKey),true);
});
test('late old watcher cannot bind or remove a new request for the same payload',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve);
 const {c,storage}=make({fetch:async()=>gate});
 let nextId=0;c.createPaidRequestId=()=>`generate-${++nextId}`;
 const body={video_file_id:'same-video'};
 const old=await c.paidSubmissionIdentity('generate',body,quote);
 c.PAID_TASK_READ_ATTEMPTS=1;c.PAID_TASK_READ_INTERVAL_MS=0;c._paidTaskWatchers=new Map();
 c.load('readPaidTaskState','watchPaidTask');
 const watched=c.watchPaidTask(old,'generate',{ownerId:'owner-a'},'synthetic-a');
 await Promise.resolve();
 c.finishPaidSubmission(old);
 const next=await c.paidSubmissionIdentity('generate',body,quote);
 assert.notEqual(next.requestId,old.requestId);
 release({ok:true,json:async()=>({tasks:[{task_id:'old-task',operation:'generate',status:'failed',billing:{status:'refunded'}}]})});
 assert.equal(await watched,null);
 c.bindPaidSubmissionReceipt(old,{request_id:'old-task'});
 c.finishPaidSubmission(old);
 assert.equal(JSON.parse(storage.get(next.storageKey)).requestId,next.requestId);
 assert.equal(JSON.parse(storage.get(next.storageKey)).serverRequestId,undefined);
});

function generationOutcomeFixture(){
 const heading={textContent:'AI 爆文生成中'},idle=[];
 const fixture=make({_activeGeneratePaidRequestId:'',_generateResult:null,_genWaitInterval:null,
   _live3DController:{setAgentState:(index,state)=>idle.push([index,state])},setLive3DMode(){},setLive3DProgress(){},
   refreshCreditBalance(){},addBubble(){}});
 const {c,elements,Element}=fixture;
 for(const id of ['mainProgress','progressLabel','generation-paid-task-banner','generate-billing-preview','page-report','generation-paid-task-status',
   ...Array.from({length:8},(_,i)=>'tl'+i),...Array.from({length:5},(_,i)=>'av'+i)]){
   const el=new Element('div'),classes=new Set();el.classList={add:(...names)=>names.forEach(n=>classes.add(n)),remove:(...names)=>names.forEach(n=>classes.delete(n)),contains:name=>classes.has(name)};
   el.querySelector=()=>({textContent:''});elements.set(id,el);
 }
 c.document.querySelector=()=>heading;c.document.querySelectorAll=()=>[];
 c.load('setProgress','stepActive','stepDone','paidTaskStatusText','renderGenerationTaskOutcome','displayPaidTaskState','_handleGenStreamEvent');
 return {...fixture,heading,idle};
}
test('refunded SSE error exits scoring activity and shows confirmed refund without inventing a cause',()=>{
 const {c,elements,heading,idle}=generationOutcomeFixture();
 c._activeGeneratePaidRequestId='original';
 c._handleGenStreamEvent({type:'stage',stage:'p4',progress:86,label:'评分验证中…'});
 elements.get('av4').classList.add('thinking','arbiter');
 c._handleGenStreamEvent({type:'error',task_status:'failed',billing:{status:'refunded'}});
 assert.equal(elements.get('tl6').classList.contains('active'),false);
 assert.equal(elements.get('av4').classList.contains('thinking'),false);
 assert.equal(elements.get('av4').classList.contains('arbiter'),false);
 assert.equal(heading.textContent,'本次爆文生成未完成');
 assert.match(elements.get('progressLabel').textContent,/积分已按原来源退回/);
 assert.doesNotMatch(elements.get('progressLabel').textContent,/质量|评分验证|正在读取/);
 assert.ok(idle.some(([index,state])=>index===4 && state==='idle'));
});
test('failed refunded task readback closes stale scoring activity and clears only its settled identity',async()=>{
 const {c,storage,elements,heading}=generationOutcomeFixture();
 const submission=await c.paidSubmissionIdentity('generate',{brief:'original'},quote);
 c._activeGeneratePaidRequestId=submission.requestId;
 c._handleGenStreamEvent({type:'stage',stage:'p4',progress:86,label:'评分验证中…'});
 assert.equal(c.displayPaidTaskState({status:'failed',refund_status:'refunded',billing:{status:'refunded'}},submission,'generate',{},'synthetic-a'),true);
 assert.equal(elements.get('tl6').classList.contains('active'),false);
 assert.equal(heading.textContent,'本次爆文生成未完成');
 assert.match(elements.get('progressLabel').textContent,/积分已按原来源退回/);
 assert.equal(storage.has(submission.storageKey),false);
});
test('unknown task readback remains unconfirmed and a late old outcome cannot change a new task display',async()=>{
 const {c,storage,elements,heading}=generationOutcomeFixture();
 const original=await c.paidSubmissionIdentity('generate',{brief:'original'},quote);
 c._activeGeneratePaidRequestId=original.requestId;
 c._handleGenStreamEvent({type:'stage',stage:'p4',progress:86,label:'评分验证中…'});
 assert.equal(c.displayPaidTaskState({status:'outcome_unknown'},original,'generate',{},'synthetic-a'),false);
 assert.equal(elements.get('tl6').classList.contains('active'),false);
 assert.equal(heading.textContent,'正在核实原任务结果');
 assert.match(elements.get('progressLabel').textContent,/尚未确认.*请勿重复提交/);
 assert.equal(c._generateResult._outcome_unknown,true);assert.equal(c._generateResult._error,undefined);
 assert.equal(storage.has(original.storageKey),true);
 const next=await c.paidSubmissionIdentity('generate',{brief:'new task'},quote);c._activeGeneratePaidRequestId=next.requestId;
 c._handleGenStreamEvent({type:'stage',stage:'p4',progress:86,label:'新任务评分验证中…'});
 const headingBefore=heading.textContent;
 c.displayPaidTaskState({status:'failed',refund_status:'refunded',billing:{status:'refunded'}},original,'generate',{},'synthetic-a');
 c.renderGenerationTaskOutcome({status:'failed',billing:{status:'refunded'}},original.requestId);
 assert.equal(elements.get('tl6').classList.contains('active'),true);
 assert.equal(elements.get('progressLabel').textContent,'新任务评分验证中…');
 assert.equal(heading.textContent,headingBefore);assert.equal(storage.has(next.storageKey),true);
});
test('account clear releases the old generation busy state before a new account can start',()=>{
 const {c,elements,Element}=generationOutcomeFixture();const cleared=[],attributes={},label={textContent:''};
 for(const id of ['diag-history-list','diag-history-count','diag-detail-section'])elements.set(id,new Element('div'));
 const button=new Element('button');button.querySelector=()=>label;button.setAttribute=(key,value)=>{attributes[key]=value;};elements.set('generateSubmitBtn',button);
 Object.assign(c,{closeVerificationModal(){},closeChangePwd(){},renderBillingReceipt(){},clearProfileUserState(){},clearTrackingUserState(){},
   resetBillingUsageState(){},clearReportSelection(){},resetScreenshot(){},localStorage:{removeItem(){}},
   clearInterval:id=>cleared.push(id),_chatRequestAbortController:null,_reportHistorySequence:0,_chatUserStateEpoch:0,_billingBalanceRevision:0,
   _activeGeneratePaidRequestId:'old-account-request',_genStreamActive:true,_genWaitInterval:77});
 c.load('_setGenerationSubmitBusy','chatClearUserState');c._setGenerationSubmitBusy(true);
 assert.equal(button.disabled,true);c.chatClearUserState();
 assert.equal(c._activeGeneratePaidRequestId,null);assert.equal(c._genStreamActive,false);
 assert.equal(button.disabled,false);assert.equal(attributes['aria-busy'],'false');
 assert.equal(c._genWaitInterval,null);assert.deepEqual(cleared,[77]);assert.equal(c._chatUserStateEpoch,1);
});
test('actual generation SSE unknown terminal keeps an unknown result and its pending identity',async()=>{
 const {c,elements,Element,storage,heading}=generationOutcomeFixture();let watched=0;
 const pending=await c.paidSubmissionIdentity('generate',{brief:'synthetic source'},quote);
 const terminal={type:'error',task_status:'outcome_unknown',refund_status:'unconfirmed',billing:{status:'unconfirmed'}};
 for(const [id,value] of [['genDomain','休闲娱乐体验'],['genBrief','synthetic source']]){const el=new Element('input');el.value=value;elements.set(id,el);}
 Object.assign(c,{PUBLIC_PRODUCT:false,requirePublicCapability:()=>true,_genStreamActive:false,_genVideoState:'empty',_genVideoFileId:null,
   _genVideoAttempt:0,_genCoverImages:[],getConstraintTags:()=>[],getContentIntentPayload:()=>({}),shouldAskMerchantBeforeRun:()=>false,
   clearReportSelection(){},_setGenerationSubmitBusy(){},formatLocalTimeWithConstraints:()=> 'synthetic-time',
   preparePaidSubmission:async()=>pending,createSseWarningGuard:()=>({connected(){},event(){},finish(){}}),
   fetch:async()=>({status:200,ok:true,body:{}}),setTimeout(){},watchPaidTask:()=>{watched++;},
   consumeJsonSse:async(_response,options)=>{options.onEvent(terminal);return {terminalEvent:terminal};}});
 c.load('paidRequest409Message','startGeneration');await c.startGeneration();await c._diagnosePromise;
 assert.equal(c._generateResult._outcome_unknown,true);assert.equal(c._generateResult._error,undefined);
 assert.equal(c._generateResult.billing.status,'unconfirmed');assert.equal(storage.has(pending.storageKey),true);
 assert.equal(heading.textContent,'正在核实原任务结果');assert.equal(watched,1);assert.equal(c._genStreamActive,false);
});
test('late completed generation timers cannot open an old report after a new same-account task begins',async()=>{
 for(const switchAt of [600,1200]){
  const {c,elements,Element}=generationOutcomeFixture(),timers=[],pages=[];
  const pending=await c.paidSubmissionIdentity('generate',{brief:'synthetic source'},quote);
  const terminal={type:'complete',note_title:'synthetic finished',note_body:'synthetic body'};
  for(const [id,value] of [['genDomain','休闲娱乐体验'],['genBrief','synthetic source']]){const el=new Element('input');el.value=value;elements.set(id,el);}
  Object.assign(c,{PUBLIC_PRODUCT:false,requirePublicCapability:()=>true,_genStreamActive:false,_genVideoState:'empty',_genVideoFileId:null,
    _genVideoAttempt:0,_genCoverImages:[],getConstraintTags:()=>[],getContentIntentPayload:()=>({}),shouldAskMerchantBeforeRun:()=>false,
    clearReportSelection(){},_setGenerationSubmitBusy(){},formatLocalTimeWithConstraints:()=> 'synthetic-time',
    preparePaidSubmission:async()=>pending,createSseWarningGuard:()=>({connected(){},event(){},finish(){}}),
    fetch:async()=>({status:200,ok:true,body:{}}),setTimeout:(run,delay)=>timers.push({run,delay}),
    completeLive3D(){},autoSaveGeneratedNote:async()=>{},showPage:page=>pages.push(page),populateReport:async()=>{},
    consumeJsonSse:async(_response,options)=>{options.onEvent(terminal);return {terminalEvent:terminal};}});
  c.load('paidRequest409Message','startGeneration');await c.startGeneration();await c._diagnosePromise;
  if(switchAt===1200)timers.find(item=>item.delay===600).run();
  c._activeGeneratePaidRequestId='new-same-account-request';c._genStreamActive=true;
  await timers.find(item=>item.delay===switchAt).run();
  assert.equal(pages.includes('report'),false);assert.equal(c._genStreamActive,true);
 }
});


test('clarification receipt binds server task identity separately and clears only that completed pending task',async()=>{
 const {c,storage}=make();const first=await c.paidSubmissionIdentity('analyze',{video_file_id:'a'},quote);
 const second=await c.paidSubmissionIdentity('analyze',{video_file_id:'b'},quote);
 c.bindPaidSubmissionReceipt(first,{request_id:'server-task-a'});c.bindPaidSubmissionReceipt(second,{request_id:'server-task-b'});
 assert.notEqual(first.requestId,first.serverRequestId);
 c.finishPendingTaskReceipt({request_id:'server-task-a',operation:'analyze',status:'charged'});
 assert.equal(storage.has(first.storageKey),false);assert.equal(storage.has(second.storageKey),true);
});
test('waiting 409 restores only the original task read and preserves identity when readback fails',async()=>{
 for(const available of [true,false]){
  let read=0,shown=0;const {c,storage}=make({API_BASE:'https://offline.invalid',_chatIdentitySnapshot:()=>({ownerId:'owner-a'}),_chatIdentityMatches:()=>true,
    showTaskClarification:()=>shown++,fetch:async(url,options)=>{read++;assert.match(url,/chat\/tasks\/server-task/);assert.equal(options.method,undefined);return {ok:available,json:async()=>available?{session_id:'server-task',operation:'analyze',status:'waiting_for_input'}:{detail:'unavailable'}};}});
  const pending=await c.paidSubmissionIdentity('analyze',{video_file_id:'video'},quote);
  const message=await c.restoreWaitingPaidSubmission({session_id:'server-task'},pending);
  assert.equal(read,1);assert.equal(shown,available?1:0);assert.equal(storage.has(pending.storageKey),true);
  assert.equal(pending.restoredTask,available?true:undefined);assert.match(message,available?/已读取原任务/:/原编号已保留/);
 }
});

async function clarificationOutcomeFixture(extra={}) {
 const fixture=generationOutcomeFixture(),{c,elements,Element}=fixture;
 const pending=await c.paidSubmissionIdentity('generate',{brief:'unknown package'},quote);
 c.bindPaidSubmissionReceipt(pending,{request_id:'original-task'});c._activeGeneratePaidRequestId=pending.requestId;
 const wrap=new Element('div'),message=new Element('p'),submit=new Element('button'),readback=new Element('button');
 const textarea=new Element('textarea'),select=new Element('select'),row=new Element('div');
 wrap.dataset={};row.dataset={questionId:'package'};textarea.value='';select.value='omitted';
 row.querySelector=selector=>selector==='textarea'?textarea:select;row.querySelectorAll=()=>[];
 wrap.querySelector=selector=>({'[data-task-message]':message,'[data-task-submit]':submit,'[data-task-readback]':readback}[selector]);
 wrap.querySelectorAll=selector=>selector==='[data-question-id]'?[row]:[textarea,select,submit];
 const area=new Element('div');area.appendChild=value=>area.append(value);elements.set('bubbleArea',area);
 c.document.createElement=()=>wrap;
 Object.assign(c,{chatEsc:value=>String(value || ''),_setGenerationSubmitBusy(){},updateDiagnosisSubmitState(){},...extra});
 c.load('renderTaskClarification');
 c.renderTaskClarification({session_id:'original-task',operation:'generate',status:'waiting_for_input',version:1,
   questions:[{question_id:'package',question:'套餐是否包含自助餐？',options:[]}]});
 return {...fixture,pending,wrap,message,submit,readback,textarea,select};
}
test('actual clarification resume failed/refunded SSE closes scoring and clears only the original settled identity',async()=>{
 let posted=0;const terminal={type:'error',task_id:'original-task',task_status:'failed',billing:{status:'refunded'}};
 const f=await clarificationOutcomeFixture({fetch:async(_url,options)=>{posted++;assert.equal(options.method,'POST');return {ok:true};},
   consumeJsonSse:async(_response,options)=>{options.onEvent({type:'stage',stage:'p4',progress:86,label:'评分验证中…'});options.onEvent(terminal);return {terminalEvent:terminal};}});
 const {c,elements,heading,storage,pending,submit,message}=f;
 const other=await c.paidSubmissionIdentity('generate',{brief:'unrelated pending'},quote);
 await submit.click();await submit.click();
 assert.equal(posted,1);assert.equal(elements.get('tl6').classList.contains('active'),false);
 assert.equal(heading.textContent,'本次爆文生成未完成');assert.match(message.textContent,/积分已按原来源退回/);
 assert.equal(c._generateResult._error,true);assert.equal(c._generateResult._outcome_unknown,undefined);
 assert.equal(storage.has(pending.storageKey),false);assert.equal(storage.has(other.storageKey),true);assert.equal(submit.disabled,true);
});
test('actual clarification unknown SSE stops scoring, retains original identity and prevents answer replay',async()=>{
 let posted=0;const f=await clarificationOutcomeFixture({fetch:async()=>{posted++;return {ok:true};},
   consumeJsonSse:async(_response,options)=>{options.onEvent({type:'stage',stage:'p4',progress:86,label:'评分验证中…'});return {terminalEvent:null};}});
 const {c,elements,heading,storage,pending,submit,message}=f;
 await submit.click();await submit.click();
 assert.equal(posted,1);assert.equal(elements.get('tl6').classList.contains('active'),false);
 assert.equal(heading.textContent,'正在核实原任务结果');assert.match(message.textContent,/尚未完成确认.*不重复提交/);
 assert.equal(c._generateResult._outcome_unknown,true);assert.equal(storage.has(pending.storageKey),true);assert.equal(submit.disabled,true);
});
test('failed clarification with an unconfirmed refund reports failure but retains the paid identity',async()=>{
 const f=await clarificationOutcomeFixture({fetch:async()=>({ok:true}),
   consumeJsonSse:async()=>({terminalEvent:{type:'error',task_status:'failed',refund_status:'pending',billing:{status:'charged'}}})});
 const {c,heading,storage,pending,submit,message}=f;await submit.click();
 assert.equal(heading.textContent,'本次爆文生成未完成');assert.equal(c._generateResult._error,true);
 assert.match(message.textContent,/正在核对本次积分退回/);assert.doesNotMatch(message.textContent,/已按原来源退回/);
 assert.equal(storage.has(pending.storageKey),true);assert.equal(submit.disabled,true);
});
test('refused clarification resume remains unknown until read-only original failed/refund readback closes it',async()=>{
 let posted=0,reads=0;const f=await clarificationOutcomeFixture({fetch:async(url,options)=>{
   if(options.method==='POST'){posted++;return {ok:false,status:409,json:async()=>({detail:'回答或任务状态已更新'})};}
   reads++;assert.match(url,/chat\/tasks\/original-task$/);return {ok:true,json:async()=>({status:'failed',refund_status:'refunded',billing:{status:'refunded'}})};
 }});
 const {c,elements,heading,storage,pending,submit,readback,message}=f;
 await submit.click();assert.equal(heading.textContent,'正在核实原任务结果');assert.equal(storage.has(pending.storageKey),true);
 await readback.click();await submit.click();
 assert.equal(posted,1);assert.equal(reads,1);assert.equal(heading.textContent,'本次爆文生成未完成');
 assert.equal(elements.get('tl6').classList.contains('active'),false);assert.match(message.textContent,/积分已按原来源退回/);
 assert.equal(c._generateResult._error,true);assert.equal(storage.has(pending.storageKey),false);assert.equal(submit.disabled,true);
});
test('late clarification failure cannot replace a newer same-account generation display or remove its pending identity',async()=>{
 let release;const response=new Promise(resolve=>release=resolve);
 const f=await clarificationOutcomeFixture({fetch:()=>response,
   consumeJsonSse:async()=>({terminalEvent:{type:'error',task_status:'failed',billing:{status:'refunded'}}})});
 const {c,elements,heading,storage,pending,submit}=f;const running=submit.click();
 const next=await c.paidSubmissionIdentity('generate',{brief:'next task'},quote);c._activeGeneratePaidRequestId=next.requestId;
 c._handleGenStreamEvent({type:'stage',stage:'p4',progress:86,label:'新任务评分验证中…'});const headingBefore=heading.textContent;
 release({ok:true});await running;
 assert.equal(heading.textContent,headingBefore);assert.equal(elements.get('tl6').classList.contains('active'),true);
 assert.equal(elements.get('progressLabel').textContent,'新任务评分验证中…');
 assert.equal(storage.has(pending.storageKey),true);assert.equal(storage.has(next.storageKey),true);
});
test('fresh running clarification read locks the old waiting form without posting another answer',async()=>{
 let reads=0,posts=0;const f=await clarificationOutcomeFixture({fetch:async(_url,options)=>{
  if(options.method==='POST'){posts++;return {ok:true};}
  reads++;return {ok:true,json:async()=>({status:'running',version:2})};
 }});
 assert.equal(f.submit.disabled,false);await f.readback.click();await f.submit.click();
 assert.equal(reads,1);assert.equal(posts,0);assert.equal(f.submit.disabled,true);
 assert.equal(f.textarea.disabled,true);assert.equal(f.select.disabled,true);assert.match(f.message.textContent,/已接收.*不重复提交/);
});
test('one clarification read holds answer submission until the original state is known',async()=>{
 let reads=0,posts=0,release;const f=await clarificationOutcomeFixture({fetch:async(_url,options)=>{
  if(options.method==='POST'){posts++;return {ok:true};}
  reads++;return new Promise(resolve=>release=resolve);
 }});
 const reading=f.readback.click();await f.readback.click();await f.submit.click();
 assert.equal(reads,1);assert.equal(posts,0);assert.equal(f.readback.disabled,true);assert.equal(f.submit.disabled,true);
 release({ok:true,json:async()=>({status:'running',version:2})});await reading;
 assert.equal(f.readback.disabled,false);assert.equal(f.submit.disabled,true);
});
test('fresh waiting read clears the stale unknown view and restores the same-question draft',async()=>{
 const state={session_id:'original-task',operation:'generate',status:'waiting_for_input',version:1,
  questions:[{question_id:'package',question:'套餐是否包含自助餐？',options:[]}]};
 const f=await clarificationOutcomeFixture({fetch:async()=>({ok:true,json:async()=>state}),
  clearReportSelection(){},rememberTaskReference(){},showPage(){}});
 f.c.chatAppendSupplementPrompts=(_items,task)=>f.c.renderTaskClarification(task);f.c.load('showTaskClarification');
 f.c._generateResult={_outcome_unknown:true};f.heading.textContent='正在核实原任务结果';
 f.elements.get('generation-paid-task-banner').style.display='block';f.textarea.value='原回答草稿';f.select.value='confirmed';
 await f.readback.click();
 assert.equal(f.heading.textContent,'补充后继续原任务');assert.equal(f.elements.get('generation-paid-task-banner').style.display,'none');
 assert.equal(f.c._generateResult._waiting_for_input,true);assert.equal(f.c._generateResult._outcome_unknown,undefined);
 assert.equal(f.textarea.value,'原回答草稿');assert.equal(f.select.value,'confirmed');assert.equal(f.submit.disabled,false);
});
test('recovery entry reads the current original task instead of enabling its stale waiting snapshot',async()=>{
 for(const status of ['running','outcome_unknown','waiting_for_input','read_failed']){
  let reads=0,shown=null;const original={session_id:'original-task',operation:'generate',status:'waiting_for_input',version:1};
  const f=make({_authVerifiedOwnerId:'owner-a',_chatOwnerId:()=> 'owner-a',_activeGeneratePaidRequestId:'original-request',localStorage:{getItem:()=>null},
   showTaskClarification:state=>{shown=state;},fetch:async(_url,options)=>{
    assert.equal(options.method,undefined);reads++;
    return reads===1?{ok:true,json:async()=>({tasks:[original]})}
      :{ok:status!=='read_failed',json:async()=>({...original,status,version:2})};
   }});
  const area=new f.Element('div');area.prepend=child=>area.children.unshift(child);f.elements.set('page-upload',area);
  f.c.document.createElement=tag=>{const e=new f.Element(tag);e.dataset={};e.appendChild=child=>e.append(child);return e;};
  f.c.load('taskReferenceKey','restorePendingTaskClarification');await f.c.restorePendingTaskClarification();
  const button=area.children[0].children[0];await button.click();
  assert.equal(reads,2);
  if(status==='read_failed'){assert.equal(shown,null);assert.equal(button.disabled,false);assert.match(button.textContent,/读回.*重试/);}
  else {assert.equal(shown.status,status);assert.equal(shown.version,2);assert.equal(shown.session_id,original.session_id);}
 }
});
test('late recovery read cannot replace a newer generation for the same account',async()=>{
 let reads=0,shown=0,release;
 const original={session_id:'original-task',operation:'generate',status:'waiting_for_input',version:1};
 const f=make({_authVerifiedOwnerId:'owner-a',_chatOwnerId:()=> 'owner-a',_activeGeneratePaidRequestId:'original-request',
  localStorage:{getItem:()=>null},showTaskClarification:()=>shown++,fetch:async()=>{
   reads++;return reads===1?{ok:true,json:async()=>({tasks:[original]})}:new Promise(resolve=>release=resolve);
  }});
 const area=new f.Element('div');area.prepend=child=>area.children.unshift(child);f.elements.set('page-upload',area);
 f.c.document.createElement=tag=>{const e=new f.Element(tag);e.dataset={};e.appendChild=child=>e.append(child);return e;};
 f.c.load('taskReferenceKey','restorePendingTaskClarification');await f.c.restorePendingTaskClarification();
 const reading=area.children[0].children[0].click();f.c._activeGeneratePaidRequestId='new-request';
 release({ok:true,json:async()=>original});await reading;
 assert.equal(reads,2);assert.equal(shown,0);assert.equal(f.c._activeGeneratePaidRequestId,'new-request');
});


// Mixed ledger split and decimal precision are verified against the integrated UI in frontend_usage_accounting.test.cjs.
// The experimental mobile menu is intentionally absent from the production-layout FI1 candidate.

test('receipt distinguishes missing credit splits from a true zero',()=>{
 const {c,elements,Element}=make();const el=new Element('div');elements.set('report-billing-receipt',el);c.load('renderBillingReceipt');
 c.renderBillingReceipt({credits_used:0,monthly_credits_used:null,status:'charged'});
 assert.match(el.children[0].textContent,/实际扣分 0 积分/);assert.match(el.children[0].textContent,/未记录/);
 c.renderBillingReceipt({credits_used:null,monthly_credits_used:0,wallet_credits_used:0,status:'charged'});
 assert.match(el.children[0].textContent,/实际扣分 未记录/);
});

test('late public capability response refreshes only current profile tracking read',async()=>{
 const calls=[];const status={style:{}};const {c}=make({PUBLIC_PRODUCT:true,_publicStatus:null,API_BASE:'https://offline.invalid',document:{getElementById:()=>status,querySelector:()=>({id:'page-profile'})},syncPublicAuthAvailability(){},syncProductUI(){},refreshNativeCapabilities(){},loadTrackingList:()=>calls.push('tracking'),fetch:async()=>({ok:true,json:async()=>({tracking_read_open:true,tracking_open:false})})});
 c.load('publicImageOpen','publicVideoOpen','profileTrackingAvailable','trackingManualAvailable','trackingDeleteAvailable','refreshPublicStatus');await c.refreshPublicStatus();assert.deepEqual(calls,['tracking']);
});

test('manual and delete capability changes refresh actions even when read permission is unchanged',async()=>{
 const calls=[];const status={style:{}};
 const {c}=make({PUBLIC_PRODUCT:true,_publicStatus:{tracking_read_open:true,tracking_manual_open:false,tracking_delete_open:false,tracking_open:false},API_BASE:'https://offline.invalid',document:{getElementById:()=>status,querySelector:()=>({id:'page-profile'})},syncPublicAuthAvailability(){},syncProductUI(){},refreshNativeCapabilities(){},loadTrackingList:()=>calls.push('tracking'),fetch:async()=>({ok:true,json:async()=>({tracking_read_open:true,tracking_manual_open:true,tracking_delete_open:true,tracking_open:false})})});
 c.load('publicImageOpen','publicVideoOpen','profileTrackingAvailable','trackingManualAvailable','trackingDeleteAvailable','refreshPublicStatus');
 await c.refreshPublicStatus();assert.deepEqual(calls,['tracking']);
});

// Explicit reservation_v1 fixtures exercise UI wording only, not real account settlement.
test('postdelivery quote keeps fixed price and starts without a dialog while disclosing reservation',async()=>{
 const {c,elements,Element}=make({fetch:async()=>({ok:true,json:async()=>({...quote,charge_timing:'after_saved_report'})})});
 const preview=new Element('div');elements.set('analyze-billing-preview',preview);
 const accepted=await c.confirmBillingQuote('analyze',false);
 assert.equal(accepted.credits,6);assert.match(preview.textContent,/受理时预留积分，报告完成并保存后扣分/);
 assert.doesNotMatch(preview.textContent,/受理时先扣/);assert.equal(elements.has('billing-quote-dialog'),false);
});
test('postdelivery receipt separates reservation, committed charge, release, and unresolved release',()=>{
 const {c,elements,Element}=make();const el=new Element('div');elements.set('report-billing-receipt',el);c.load('renderBillingReceipt');
 const base={settlement_mode:'reservation_v1',credits_used:0,monthly_credits_used:0,wallet_credits_used:0,refunded_credits:0};
 c.renderBillingReceipt({...base,status:'reserved',reserved_credits:8,monthly_credits_reserved:6,wallet_credits_reserved:2});
 assert.match(el.children[0].textContent,/预留 8 积分.*周期 6 \+ 充值 2.*当前未扣积分/);assert.doesNotMatch(el.children[0].textContent,/实际扣分|退回/);
 c.renderBillingReceipt({...base,status:'reserved',refund_status:'pending',reserved_credits:8});
 assert.match(el.children[0].textContent,/待后台确认释放.*当前未扣积分/);assert.doesNotMatch(el.children[0].textContent,/已释放|已退/);
 c.renderBillingReceipt({...base,status:'released',released_credits:8});
 assert.match(el.children[0].textContent,/预留 8 积分已释放，本次未扣积分/);assert.doesNotMatch(el.children[0].textContent,/退回|实际扣分/);
 c.renderBillingReceipt({...base,status:'committed',credits_used:8,monthly_credits_used:6,wallet_credits_used:2});
 assert.match(el.children[0].textContent,/报告已保存，本次实际扣分 8 积分.*周期 6 \+ 充值 2/);
 c.renderBillingReceipt({...base,status:'unexpected'});assert.match(el.children[0].textContent,/结算状态待核实/);
});
test('postdelivery failed task resolves only confirmed release and preserves legacy refund language',()=>{
 const {c}=make();c.load('paidTaskStatusText');
 const pending={status:'failed',refund_status:'pending',billing:{settlement_mode:'reservation_v1',status:'reserved'}};
 assert.equal(c.paidTaskFundsResolved(pending),false);assert.match(c.paidTaskStatusText(pending,'generate'),/正在核实预留积分释放，本次尚未扣积分/);
 const released={...pending,refund_status:'released',billing:{settlement_mode:'reservation_v1',status:'released'}};
 assert.equal(c.paidTaskFundsResolved(released),true);assert.match(c.paidTaskStatusText(released,'generate'),/预留积分已释放，本次未扣积分/);
 assert.equal(c.paidTaskFundsResolved({...pending,refund_status:'refunded'}),false);
 assert.match(c.paidTaskStatusText({status:'failed',refund_status:'refunded',billing:{status:'refunded'}},'analyze'),/已按原来源退回/);
 assert.doesNotMatch(c.paidTaskStatusText({status:'failed',billing:{settlement_mode:'reservation_v1',status:'committed'}},'generate'),/尚未扣|已释放|退回/);
});

test('confirmed reservation release permits one explicit new identity while pending release does not',async()=>{
 for(const released of [false,true]){
  let quoted=0;const billing={settlement_mode:'reservation_v1',status:released?'released':'reserved'};
  const {c}=make({readPaidTaskState:async()=>({status:'failed',refund_status:released?'released':'pending',billing})});
  const old=await c.paidSubmissionIdentity('generate',{brief:'same-public-fixture'},quote);
  c.displayPaidTaskState=(task,submission)=>{if(c.paidTaskFundsResolved(task))c.finishPaidSubmission(submission);};
  c.confirmBillingQuote=async()=>{quoted++;return quote;};
  const next=await c.preparePaidSubmission('generate',{brief:'same-public-fixture'});
  assert.equal(quoted,released?1:0);
  if(released){assert.ok(next?.requestId);assert.notEqual(next.requestId,old.requestId);}else assert.equal(next,null);
 }
});
