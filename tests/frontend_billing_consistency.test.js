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
 const body=new Element('body');const c=vm.createContext({console,window:{},crypto:crypto.webcrypto,TextEncoder,Uint8Array,_authUser:{id:'owner-a'},_authToken:'synthetic-a',_billingQuoteBusy:false,API_AUTH:'https://offline.invalid',authHeader:()=>({Authorization:'Bearer synthetic'}),showToast(){},openAuthModal(){},showQuotaExceededModal(){},openCreditRecords(){},sessionStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),body},...extra});
 c.load=(...names)=>names.forEach(name=>vm.runInContext(source(name),c));c.load('createPaidRequestId','paidSubmissionIdentity','finishPaidSubmission','confirmBillingQuote','pendingPaidSubmissions','preparePaidSubmission','bindPaidSubmissionReceipt','finishPendingTaskReceipt','restoreWaitingPaidSubmission');return {c,storage,elements,Element};
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


test('unknown original can be verified after its first charge exhausts balance without a new quote',async()=>{
 let quoted=0,confirmed=0;const {c}=make({confirm:text=>{confirmed++;assert.match(text,/不会作为新任务再次扣分/);return true;},fetch:async()=>{quoted++;throw Error('new quote must not be requested');}});
 const original={video_file_id:'same-video',local_time:'2026091710'};
 const pending=await c.paidSubmissionIdentity('analyze',original,quote);
 const retry={...original,local_time:'2026091711'};
 const restored=await c.preparePaidSubmission('analyze',retry);
 assert.equal(restored.requestId,pending.requestId);assert.deepEqual(retry,original);assert.equal(quoted,0);assert.equal(confirmed,1);
});
test('different material reference warns about unresolved original before allowing any new quote',async()=>{
 let quoted=0;const {c}=make({confirm:text=>{assert.match(text,/重新上传/);return false;},fetch:async()=>{quoted++;throw Error('must not quote');}});
 await c.paidSubmissionIdentity('analyze',{video_file_id:'original'},quote);
 assert.equal(await c.preparePaidSubmission('analyze',{video_file_id:'new-upload-ref'}),null);assert.equal(quoted,0);
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
 c.load('publicImageOpen','publicVideoOpen','profileTrackingAvailable','refreshPublicStatus');await c.refreshPublicStatus();assert.deepEqual(calls,['tracking']);assert.match(status.textContent,/新增追踪暂未开放/);
});
