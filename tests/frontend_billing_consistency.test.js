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
 c.load=(...names)=>names.forEach(name=>vm.runInContext(source(name),c));c.load('createPaidRequestId','paidSubmissionIdentity','currentPaidSubmission','finishPaidSubmission','confirmBillingQuote','pendingPaidSubmissions','generationVideoExpiryMessage','generationVideoSubmissionMessage','showGenerationVideoSubmissionMessage','preparePaidSubmission','bindPaidSubmissionReceipt','finishPendingTaskReceipt','restoreWaitingPaidSubmission');return {c,storage,elements,Element};
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
test('quota dialog uses server totals and confirmation, never a client price in request',async()=>{
 let request;const {c,elements}=make({fetch:async(url,options)=>{request={url,options};return {ok:true,json:async()=>quote};}});
 const pending=c.confirmBillingQuote('analyze',true);while(!elements.has('billing-quote-confirm'))await new Promise(r=>setImmediate(r));
 assert.equal(elements.get('billing-quote-confirm').textContent,'确认并提交 · 6 积分');assert.match(request.url,/has_video=true/);assert.equal(request.options.body,undefined);
 elements.get('billing-quote-confirm').click();const accepted=await pending;assert.equal(accepted.quote_version,'server-six');assert.equal(c._billingQuoteBusy,false);
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
test('only proven refund clears pending stream errors; ambiguous errors retain identity',()=>{
 for(const name of ['startGeneration','prepareDiagnosis']){
  const code=source(name);assert.match(code,/terminal\.billing\?\.status === 'refunded'\) finishPaidSubmission/);assert.match(code,/'X-Billing-Quote-Version': submission.quoteVersion/);assert.match(code,/preparePaidSubmission\(/);
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
 c.load('publicImageOpen','publicVideoOpen','profileTrackingAvailable','trackingManualAvailable','trackingDeleteAvailable','refreshPublicStatus');await c.refreshPublicStatus();assert.deepEqual(calls,['tracking']);assert.match(status.textContent,/新增追踪暂未开放/);
});

test('manual and delete capability changes refresh actions even when read permission is unchanged',async()=>{
 const calls=[];const status={style:{}};
 const {c}=make({PUBLIC_PRODUCT:true,_publicStatus:{tracking_read_open:true,tracking_manual_open:false,tracking_delete_open:false,tracking_open:false},API_BASE:'https://offline.invalid',document:{getElementById:()=>status,querySelector:()=>({id:'page-profile'})},syncPublicAuthAvailability(){},syncProductUI(){},refreshNativeCapabilities(){},loadTrackingList:()=>calls.push('tracking'),fetch:async()=>({ok:true,json:async()=>({tracking_read_open:true,tracking_manual_open:true,tracking_delete_open:true,tracking_open:false})})});
 c.load('publicImageOpen','publicVideoOpen','profileTrackingAvailable','trackingManualAvailable','trackingDeleteAvailable','refreshPublicStatus');
 await c.refreshPublicStatus();assert.deepEqual(calls,['tracking']);assert.match(status.textContent,/手工记录互动数据，未经平台核验/);assert.match(status.textContent,/自动采集暂未开放/);
});
