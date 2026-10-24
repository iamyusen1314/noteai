const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
const html=fs.readFileSync(require('node:path').join(__dirname,'../NoteAI_Pro_Demo_Framer.html'),'utf8');
const code=html.split('/* ── Independent saved-report cover tasks ───────────────────── */')[1].split('/* ── Generation report populate')[0];
function make(extra={}) {
 const storage=new Map(),calls=[],elements=new Map();
 const el=name=>{if(!elements.has(name))elements.set(name,{textContent:'',value:name==='position'?'top':'',hidden:false,disabled:false,src:'',replaceChildren(...children){this.children=children;this.value=children[0]?.value || '';}});return elements.get(name);};
 const dialog={isConnected:true,open:true,querySelector:selector=>el(selector.match(/"([^"]+)"/)[1]),querySelectorAll:()=>[],close(){this.open=false;},remove(){this.isConnected=false;}};
 let identity=true;
 const c=vm.createContext({console:{...console,warn(){}},document:{createElement:()=>({value:'',textContent:''})},crypto:crypto.webcrypto,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  _historyReportSelection:{report_type:'generate',report_id:'saved-report'},_authToken:'synthetic-token',_authUser:{id:'synthetic-owner'},
  reportIsGeneration:()=>true,reportGenerationResult:()=>null,reportDiagnosisResult:()=>null,completeProductResult:x=>!!x,
  productActionAttributes:()=>'',_chatIdentitySnapshot:()=>({ownerId:'synthetic-owner',epoch:1}),_chatIdentityMatches:()=>identity,
  _fmtLocalTime:x=>x,refreshCreditBalance:async()=>null,FormData,URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:x=>calls.push(['revoke',x])},
  clearTimeout:x=>calls.push(['clear',x]),setTimeout:()=>99,API_BASE:'http://offline.invalid',showToast(){},...extra});
 vm.runInContext(code,c);
 const ctx={dialog,report_type:'generate',report_id:'saved-report',identity:{ownerId:'synthetic-owner'},token:'synthetic-token',path:'/reports/generate/saved-report',
  urls:new Set(),selected:new Set(['11111111-1111-4111-8111-111111111111']),sources:[],enabled:true,quote:{operation:'cover_generate',credits:8,quote_version:'cover-v1',can_afford:true,charge_timing:'after_saved_cover'},current:()=>identity&&dialog.isConnected};
 c.ctx=ctx;vm.runInContext('_coverPanel=ctx',c);
 return {c,ctx,calls,storage,elements,el,leave:()=>identity=false};
}
const completed={job_id:'job-original',request_id:'11111111-1111-4111-8111-111111111111',report_type:'generate',report_id:'saved-report',status:'completed',stage:'completed',has_final:true,asset_revision:1,layout:{text:'真实标题',position:'top',position_options:['top','bottom']},billing:{status:'committed',credits_used:8},expires_at:'2027-01-18T00:00:00Z'};
test('fresh report identity never guesses a generation report from title or note id',()=>{
 const {c}=make();c._historyReportSelection=null;c.reportGenerationResult=()=>({note_title:'same title',saved_note_id:'not-a-report'});
 assert.equal(c.coverReportRef('generate'),null);
 c.reportGenerationResult=()=>({billing:{operation:'generate',request_id:'server-request'}});assert.equal(c.coverReportRef('generate').report_id,'server-request');
 c.reportDiagnosisResult=()=>({diagnosis_id:'original-diagnosis'});assert.equal(c.coverReportRef('analyze').report_id,'original-diagnosis');
});
test('missing, changed-operation and unaffordable quotes never enable an independent cover call',async()=>{
 for(const quote of [null,{credits:0},{operation:'generate',credits:8},{operation:'cover_generate',credits:8,quote_version:'v',can_afford:false,charge_timing:'after_saved_cover'}]) {
  let posts=0;const {c,ctx}=make({fetch:async()=>{posts++;throw Error('must not submit');}});ctx.quote=quote;
  await c.coverCreate(ctx);assert.equal(posts,0);assert.equal(ctx.pending,undefined);
 }
});
test('rapid clicks share one UUID request and a lost ACK blocks automatic paid resubmission',async()=>{
 let calls=0,release;const gate=new Promise(r=>release=r);const {c,ctx,storage}=make({fetch:async()=>{calls++;await gate;throw Error('response lost');}});
 const first=c.coverCreate(ctx);await Promise.resolve();await c.coverCreate(ctx);release();await first;
 assert.equal(calls,1);assert.match(ctx.pending.request_id,/^[0-9a-f-]{36}$/);
 await c.coverCreate(ctx);assert.equal(calls,1);assert.equal(storage.size,1);
 const saved=[...storage.values()].join();assert.ok(saved.includes('11111111-1111-4111-8111-111111111111'));assert.ok(!saved.includes('synthetic-token'));assert.ok(!saved.includes('base64'));assert.ok(!saved.includes('真实标题'));
});
test('a conflicting or 5xx response remains unresolved instead of creating a fresh paid request',async()=>{
 for(const status of [409,500,503]) {
  let posts=0;const {c,ctx}=make({fetch:async()=>{posts++;return {ok:false,status,json:async()=>({detail:'核查原请求'})};}});
  await c.coverCreate(ctx);assert.ok(ctx.pending);await c.coverCreate(ctx);assert.equal(posts,1);
 }
});
test('an unresolved new request never borrows an older task billing receipt',async()=>{
 for(const billing of [{status:'released',reserved_credits:0},{status:'committed',credits_used:8}]) {
  let posts=0,found=false;
  const older={...completed,job_id:'older-task',status:billing.status==='released'?'failed':'completed',has_final:billing.status==='committed',billing};
  const {c,ctx,el}=make({fetch:async(url,options={})=>{
   if(options.method==='POST'){posts++;return {ok:false,status:503,json:async()=>({detail:'核查原请求'})};}
   const jobs=found?[{...completed,job_id:'new-task',request_id:ctx.pending.request_id,status:'queued',stage:'queued',has_final:false,billing:{status:'reserved',reserved_credits:8}}]:[older];
   return {ok:true,json:async()=>({enabled:true,quote:ctx.quote,jobs,latest_success:ctx.latest})};
  }});
  const saved=older.has_final?older:completed;
  c.coverAcceptJob(ctx,older);ctx.latest={...saved};ctx.previewKey=saved.job_id+':'+saved.asset_revision;
  await c.coverCreate(ctx);const original=ctx.pending.request_id;
  assert.match(el('status').textContent,/受理结果待核查/);
  assert.doesNotMatch(el('status').textContent,/预留已释放|实际扣分/);
  await c.coverRefresh(ctx);
  assert.equal(ctx.pending.request_id,original);assert.equal(posts,1);
  assert.doesNotMatch(el('status').textContent,/预留已释放|实际扣分/);
  assert.equal(ctx.latest.job_id,saved.job_id);
  found=true;await c.coverRefresh(ctx);
  assert.equal(ctx.pending,null);assert.equal(posts,1);
  assert.match(el('status').textContent,/已预留 8 积分，尚未扣分/);
 }
});
test('unconfirmed admission retains only request identity, HTTP status and fixed error type in diagnostics',async()=>{
 const privateText='do-not-log-token-title-media-or-server-detail';
 for(const [fetch,status,type] of [
  [async()=>({ok:false,status:503,json:async()=>({detail:privateText})}),503,'Error'],
  [async()=>({ok:true,status:202,json:async()=>{throw new SyntaxError(privateText);}}),202,'SyntaxError'],
  [async()=>{throw new TypeError(privateText);},null,'TypeError']
 ]) {
  const events=[];let posts=0;
  const {c,ctx}=make({console:{warn:(...args)=>events.push(args)},fetch:async(...args)=>{posts++;return fetch(...args);}});
  await c.coverCreate(ctx);const original=ctx.pending.request_id;await c.coverCreate(ctx);
  assert.equal(posts,1);assert.equal(events.length,1);
  assert.equal(events[0].length,1);assert.equal(typeof events[0][0],'string');
  assert.ok(events[0][0].startsWith('noteai_cover_admission_unconfirmed '));
  const data=JSON.parse(events[0][0].slice('noteai_cover_admission_unconfirmed '.length));
  assert.deepEqual(data,{request_id:original,phase:'create',http_status:status,error_type:type});
  assert.ok(!JSON.stringify(events).includes(privateText));assert.ok(!JSON.stringify(events).includes('synthetic-token'));
 }
});
test('explicit recovery diagnostics distinguish lookup from the one original-wire submission',async()=>{
 for(const mode of ['lookup-503','submit-503','submit-network']) {
  const events=[];let first=true,posts=0;
  const {c,ctx}=make({console:{warn:(...args)=>events.push(args)},fetch:async(url,options={})=>{
   if(options.method==='POST')posts++;
   if(first){first=false;throw new TypeError('private-initial-error');}
   if(!options.method && mode!=='lookup-503')return {ok:true,status:200,json:async()=>({jobs:[]})};
   if(mode==='submit-network')throw new TypeError('private-submission-error');
   return {ok:false,status:503,json:async()=>({detail:'private-server-detail'})};
  }});
  await c.coverCreate(ctx);const original=ctx.pending.request_id;await c.coverRecoverPending(ctx);
  assert.equal(events.length,2);assert.equal(ctx.pending.request_id,original);
  assert.equal(events[1].length,1);assert.equal(typeof events[1][0],'string');
  assert.ok(events[1][0].startsWith('noteai_cover_admission_unconfirmed '));
  const data=JSON.parse(events[1][0].slice('noteai_cover_admission_unconfirmed '.length));
  assert.deepEqual(data,{request_id:original,phase:mode==='lookup-503'?'recovery_lookup':'recovery_submit',http_status:mode==='submit-network'?null:503,error_type:mode==='submit-network'?'TypeError':'Error'});
  assert.equal(posts,mode==='lookup-503'?1:2);await c.coverCreate(ctx);assert.equal(posts,mode==='lookup-503'?1:2);
  assert.ok(!JSON.stringify(events).includes('private-'));assert.ok(!JSON.stringify(events).includes('synthetic-token'));
 }
});
test('a saved task is recovered by server request identity and disabled submission still permits the saved preview',async()=>{
 const {c,ctx,storage,el}=make();c.coverWritePending(ctx,{request_id:completed.request_id,quote_version:'v'});
 c.fetch=async url=>url.includes('/download')?{ok:true,blob:async()=>new Blob(['synthetic'],{type:'image/png'})}:{ok:true,json:async()=>({enabled:false,reason:'暂时关闭新提交',quote:null,jobs:[completed],latest_success:completed})};
 await c.coverRefresh(ctx);assert.equal(ctx.latest.job_id,'job-original');assert.equal(ctx.pending,null);assert.equal(storage.size,0);
 assert.equal(el('create').disabled,true);assert.equal(el('result').hidden,false);assert.equal(el('adjust').disabled,false);assert.equal(el('download').disabled,false);
 assert.match(el('status').textContent,/实际扣分 8/);assert.equal(el('final-image').src,'blob:synthetic');
});
test('unavailable older preview cannot turn an accepted new task into an unconfirmed submission',async()=>{
 let posts=0,downloads=0,poll;const events=[];
 const {c,ctx,el}=make({setTimeout:callback=>{poll=callback;return 99;},console:{warn:x=>events.push(x)},fetch:async(url,options={})=>{
  if(url.includes('/download')){downloads++;return {ok:false,status:503,json:async()=>({detail:'封面存储暂不可用'})};}
  const running={...completed,job_id:'new-task',request_id:options.body?JSON.parse(options.body).request_id:ctx.active.request_id,status:'running',stage:'design',has_final:false,billing:{status:'reserved',reserved_credits:8}};
  if(options.method==='POST'){posts++;return {ok:true,status:202,json:async()=>running};}
  return {ok:true,json:async()=>({...running,stage:'qc'})};
 }});
 ctx.latest={...completed};await c.coverCreate(ctx);
 assert.equal(posts,1);assert.equal(ctx.active.job_id,'new-task');assert.equal(ctx.pending,null);assert.equal(events.length,0);
 assert.match(el('status').textContent,/正在选图与设计.*\n已预留 8/);assert.match(el('preview-note').textContent,/预览暂不可用/);
 assert.equal(downloads,1);assert.equal(typeof poll,'function');await poll();
 assert.match(el('status').textContent,/正在检查设计、文字与真实主体/);assert.equal(downloads,1);assert.equal(posts,1);
});
test('manual refresh retries only the unavailable preview and keeps the reserved task recoverable',async()=>{
 let downloads=0,ready=false,poll;
 const running={...completed,job_id:'new-task',status:'running',stage:'design',has_final:false,billing:{status:'reserved',reserved_credits:8}};
 const {c,ctx,el}=make({setTimeout:callback=>{poll=callback;return 99;},fetch:async url=>{
  if(url.includes('/download')){downloads++;return ready?{ok:true,blob:async()=>new Blob(['fixture'],{type:'image/png'})}:{ok:false,status:503,json:async()=>({detail:'封面存储暂不可用'})};}
  return {ok:true,json:async()=>({enabled:true,quote:{...ctx.quote,can_afford:false},jobs:[running,completed],latest_success:completed})};
 }});
 await c.coverRefresh(ctx);assert.equal(ctx.active.job_id,'new-task');assert.equal(downloads,1);assert.equal(typeof poll,'function');
 assert.equal(el('availability').textContent,'');assert.match(el('status').textContent,/正在选图与设计/);assert.equal(el('create').disabled,true);
 ready=true;await c.coverRefresh(ctx);assert.equal(downloads,2);assert.equal(el('preview-note').textContent,'');assert.equal(el('final-image').src,'blob:synthetic');
 assert.equal(ctx.active.job_id,'new-task');assert.match(el('status').textContent,/已预留 8 积分/);
});
test('late responses from a switched account cannot publish original cover bytes or state',async()=>{
 let release;const gate=new Promise(r=>release=r);const {c,ctx,leave}=make({fetch:async()=>{await gate;return {ok:true,json:async()=>completed};}});
 const request=c.coverFetch(ctx,'/covers/job-original').catch(e=>e.message);leave();release();assert.equal(await request,'账户或报告已切换');
 assert.equal(ctx.latest,undefined);
});
test('closing the panel revokes local previews and stops polling without cancelling the server task',()=>{
 const {c,ctx,calls}=make();ctx.urls.add('blob:old');ctx.timer=41;c.closeCoverPanel();assert.equal(ctx.dialog.isConnected,false);
 assert.deepEqual(calls,[['clear',41],['revoke','blob:old']]);
});
test('free adjustment uses the original job and expected revision; save failure preserves the previous cover',async()=>{
 let request;const {c,ctx,el}=make({fetch:async(url,options)=>{request={url,options};return {ok:false,status:503,json:async()=>({detail:'保存失败'})};}});
 ctx.latest={...completed};el('text').value='真实\n新标题';el('position').value='bottom';
 await c.coverAdjust(ctx);assert.equal(ctx.latest.asset_revision,1);assert.equal(ctx.latest.job_id,'job-original');
 assert.equal(request.url,'http://offline.invalid/covers/job-original/adjust');
 assert.deepEqual(JSON.parse(request.options.body),{text:'真实\n新标题',position:'bottom',expected_revision:1});
 assert.equal(request.options.headers.Authorization,'Bearer synthetic-token');assert.match(ctx.notice,/保留上一张成功封面/);
});
test('old successful cover remains available while a later generation fails',()=>{
 const {c,ctx}=make();ctx.latest={...completed};c.coverAcceptJob(ctx,{...completed,job_id:'new-failure',request_id:'other',status:'failed',has_final:false});
 assert.equal(ctx.latest.job_id,'job-original');assert.equal(ctx.active.job_id,'new-failure');
});
test('both visual expert renderers provide one common entry and usage gives covers their own label',()=>{
 assert.equal((html.match(/\['视觉分析师','视觉专家'\]\.includes\(role\) \? coverEntryMarkup\('generate'\)/g)||[]).length,1);
 assert.equal((html.match(/role === '视觉专家' \? coverEntryMarkup\('analyze'\)/g)||[]).length,1);
 assert.match(html,/cover_generate:'笔记封面'/);assert.ok(!code.includes('/cancel'));assert.ok(!code.includes('data:image'));
});
test('actual generation report render binds both visual roles to the report and excludes incomplete or cross-type entries',async()=>{
 // Execute production rendering and identity helpers; the DOM below only collects their output.
 function source(name) {
  const start=new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(html);
  assert.ok(start,`production function ${name}`);
  for(let end=html.indexOf('}',start.index);end>=0;end=html.indexOf('}',end+1)) {
   const candidate=html.slice(start.index,end+1);
   try {new vm.Script(candidate);return candidate;} catch {}
  }
  throw Error(`Incomplete production function ${name}`);
 }
 const helpers=['escapeHtml','productActionAttributes','completeProductResult','reportGenerationResult','reportDiagnosisResult','reportIsGeneration','gradeInfo','populateGenerateReport'].map(source).join('\n');
 async function render(role,{saved=false,incomplete={},crossType=false}={}) {
  const nodes=new Map();
  const get=id=>{if(!nodes.has(id))nodes.set(id,{style:{},innerHTML:'',textContent:''});return nodes.get(id);};
  const report={note_title:'本人真实素材标题',note_body:'本人真实素材正文',saved_note_id:'never-use-note-id',ces_percentile:69,
   billing:{operation:'generate',request_id:'generated-report-id'},...incomplete,
   expert_opinions:[{role,opinion:'真实画面建议'},{role:'内容创作师',opinion:'正文建议'},{role:'增长策略师',opinion:'增长建议'}]};
  let networkCalls=0;
  const {c}=make({document:{getElementById:get,querySelector:get},_generateResult:report,_diagnoseResult:null,_isGenerateMode:true,_diagnosePromise:null,
   _historyReportSelection:crossType?{report_type:'analyze',report_id:'other-diagnosis',result:{diagnosis_id:'other-diagnosis'}}:
    saved?{report_type:'generate',report_id:'saved-clarified-report-id',result:report}:null,
   renderBillingReceipt(){},renderGenerationHeader(){},renderProviderAnswer(){},renderReportLifecycle(){},updateScoreRing(){},
   reportTimeLabel:()=>'',expertOpinionHistoryNotice:()=>'',fetch:async()=>{networkCalls++;throw Error('render must not use a transport');}});
  vm.runInContext(helpers,c);await c.populateGenerateReport();assert.equal(networkCalls,0);
  return get('genAgentResultsList').innerHTML;
 }
 for(const [role,saved,reportId] of [['视觉分析师',false,'generated-report-id'],['视觉专家',true,'saved-clarified-report-id']]) {
  const rendered=await render(role,{saved});
  const entries=[...rendered.matchAll(/data-product-action="openCoverPanel" data-product-args="([^"]*)"/g)];
  assert.equal(entries.length,1,`${role} must expose exactly one real report entry`);
  assert.deepEqual(JSON.parse(entries[0][1].replace(/&quot;/g,'"').replace(/&amp;/g,'&')),['generate',reportId]);
  const cards=rendered.split('<div class="agent-result">').slice(1);assert.equal(cards.length,3);
  for(const card of cards) assert.equal(card.includes('data-product-action="openCoverPanel"'),card.includes(`class="agent-result-name">${role}</span>`));
 }
 assert.doesNotMatch(await render('用户心理师'),/data-product-action="openCoverPanel"/);
 for(const incomplete of [{_waiting_for_input:true},{_outcome_unknown:true},{_error:true}])
  assert.doesNotMatch(await render('视觉专家',{saved:true,incomplete}),/data-product-action="openCoverPanel"/);
 assert.doesNotMatch(await render('视觉专家',{crossType:true}),/data-product-action="openCoverPanel"/);
});

test('UNKNOWN stays blocked until release; explicit new intent creates a new UUID and retains the original unknown',async()=>{
 let posts=0;const {c,ctx,el}=make({fetch:async(url,options)=>{posts++;const body=JSON.parse(options.body);return {ok:true,json:async()=>({...completed,job_id:body.request_id,request_id:body.request_id,status:'queued',has_final:false,billing:{status:'reserved',reserved_credits:8}})};}});
 const original={...completed,job_id:'unknown-original',status:'outcome_unknown',has_final:false,billing:{status:'reserved',reserved_credits:8}};
 c.coverAcceptJob(ctx,original);c.coverRender(ctx);assert.equal(el('create').disabled,true);await c.coverCreate(ctx);assert.equal(posts,0);
 c.coverAcceptJob(ctx,{...original,billing:{status:'released',reserved_credits:0}});c.coverRender(ctx);
 assert.equal(el('create').disabled,false);assert.equal(el('create').textContent,'新建封面 · 8 积分');assert.equal(posts,0);
 await c.coverCreate(ctx);assert.equal(posts,1);assert.notEqual(ctx.active.request_id,original.request_id);
 assert.ok(ctx.jobs.some(job=>job.job_id==='unknown-original'&&job.status==='outcome_unknown'));assert.match(el('unknown-history').textContent,/供应商结果仍待核查.*不追扣原任务/);
});
test('expired report source404 cannot hide its already delivered 90-day cover',async()=>{
 const {c,ctx,el}=make({fetch:async()=>({ok:false,status:404,json:async()=>({detail:'原报告已到期'})})});ctx.latest={...completed};ctx.sources=[];
 await c.coverLoadSources(ctx);assert.equal(ctx.latest.job_id,completed.job_id);assert.equal(ctx.sourceAccessExpired,true);assert.notEqual(ctx.sourceStatus,'storage_unavailable');
 c.coverRender(ctx);assert.equal(el('result').hidden,false);assert.equal(el('download').disabled,false);assert.match(el('source-note').textContent,/已有封面仍可.*重开/);
});
test('saved cover opens independently of expired report, without reading its original body or source bytes',async()=>{
 const calls=[];const {c,ctx,el}=make({fetch:async url=>{calls.push(url);return url.includes('/download')?{ok:true,blob:async()=>new Blob(['fixture'],{type:'image/png'})}:{ok:true,json:async()=>completed};}});
 c._historyReportSelection=null;c.reportGenerationResult=()=>null;ctx.savedOnly=true;ctx.savedJobId=completed.job_id;ctx.latest={...completed};
 assert.equal(c.coverSavedJobReadable(completed),true);assert.equal(c.coverSavedJobReadable({...completed,status:'failed'}),false);
 await c.coverRefresh(ctx);await c.coverLoadSources(ctx);assert.equal(ctx.latest.job_id,completed.job_id);assert.equal(el('source-form').hidden,true);
 assert.equal(el('download').disabled,false);assert.ok(calls.every(url=>url.includes('/covers/job-original')));assert.equal(calls.some(url=>url.includes('/reports/')),false);
});
test('initial title accepts only existing original and variant choices and leaves shortening to design',async()=>{
 let posts=0;const {c,ctx,el}=make({fetch:async()=>{posts++;throw Error('must not submit arbitrary text');}});
 c.reportGenerationResult=()=>({note_title:'真实原题',title_variants:['已有备选','真实原题',{title:'对象不透传'}]});
 assert.deepEqual([...c.coverTitleChoices('generate')],['真实原题','已有备选']);ctx.titleChoices=c.coverTitleChoices('generate');
 el('title').value='任意新设施文案';await c.coverCreate(ctx);assert.equal(posts,0);assert.equal(ctx.pending,undefined);
 el('title').value='已有备选';const body=c.coverSubmitBody(ctx,{request_id:'original-id',quote_version:'v'});assert.equal(body.title,'已有备选');
 el('title').value='';assert.equal(c.coverSubmitBody(ctx,{request_id:'original-id',quote_version:'v'}).title,undefined);
});
test('only explicit quote or balance rejection proving no admission and no hold clears the pending key',async()=>{
 for(const [status,code] of [[409,'BILLING_QUOTE_CHANGED'],[402,'QUOTA_EXCEEDED']]){
  const {c,ctx,storage}=make({fetch:async()=>({ok:false,status,json:async()=>({detail:{code,message:'明确未受理',admitted:false,reserved_credits:0}})})});
  await c.coverCreate(ctx);assert.equal(ctx.pending,null);assert.equal(storage.size,0);assert.equal(ctx.quote,null);assert.match(ctx.notice,/未受理、未预留/);
 }
 for(const [status,detail] of [[429,{code:'BUSY'}],[503,{code:'UNAVAILABLE'}],[402,{code:'QUOTA_EXCEEDED',admitted:true,reserved_credits:8}]]){
  const {c,ctx}=make({fetch:async()=>({ok:false,status,json:async()=>({detail})})});await c.coverCreate(ctx);assert.ok(ctx.pending);
 }
});
test('explicit recovery checks original list first then resends identical body and UUID, never a new request',async()=>{
 const requests=[];let first=true;
 const {c,ctx,el}=make({fetch:async(url,options={})=>{
  requests.push({url,method:options.method||'GET',body:options.body});
  if(first){first=false;throw Error('ACK lost before admission');}
  if(!options.method)return {ok:true,json:async()=>({jobs:[]})};
  const body=JSON.parse(options.body);return {ok:true,json:async()=>({...completed,request_id:body.request_id,status:'queued',has_final:false})};
 }});ctx.titleChoices=['真实原题'];el('title').value='真实原题';await c.coverCreate(ctx);const original=ctx.pending.request_id;
 // Even if an external page script changes the form, recovery uses frozen memory.
 el('title').value='改动后不同内容';ctx.selected.clear();await c.coverRecoverPending(ctx);
 assert.deepEqual(requests.map(r=>r.method),['POST','GET','POST']);assert.equal(requests[0].body,requests[2].body);assert.equal(JSON.parse(requests[2].body).request_id,original);assert.equal(ctx.pending,null);
});
test('legacy metadata without wire remains lookup-only; an admitted original is only read',async()=>{
 let posts=0;const {c,ctx}=make({fetch:async(url,options={})=>{if(options.method)posts++;return {ok:true,json:async()=>({jobs:[]})};}});
 c.coverWritePending(ctx,{request_id:completed.request_id,quote_version:'v'});await c.coverRecoverPending(ctx);assert.equal(posts,0);assert.ok(ctx.pending);assert.match(ctx.notice,/旧记录缺少可恢复提交内容/);
 c.fetch=async()=>({ok:true,json:async()=>({jobs:[completed]})});await c.coverRecoverPending(ctx);assert.equal(posts,0);assert.equal(ctx.pending,null);assert.equal(ctx.latest.job_id,completed.job_id);
});
test('free adjustment offers only safe backend positions plus null to retain the existing placement',async()=>{
 let request;const {c,ctx,el}=make({fetch:async(url,options)=>{request={url,options};return {ok:false,status:503,json:async()=>({detail:'保存失败'})};}});
 ctx.latest={...completed,layout:{...completed.layout,position_options:['bottom','unsafe']}};c.coverRender(ctx);
 assert.match(el('position').innerHTML,/保留当前位置/);assert.match(el('position').innerHTML,/value="bottom"/);assert.doesNotMatch(el('position').innerHTML,/value="top"|unsafe/);
 el('text').value='免费改字';await c.coverAdjust(ctx);assert.equal(JSON.parse(request.options.body).position,null);
 request=null;el('position').value='top';await c.coverAdjust(ctx);assert.equal(request,null);
});
test('usage displays per-image estimates and unconfirmed bills separately from token metering',()=>{
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',querySelectorAll:()=>[]});return nodes.get(id);};
 const {c}=make({document:{getElementById:get},escapeHtml:x=>String(x).replace(/</g,'&lt;'),fmtTokens:x=>String(x)});
 const start=html.indexOf('let _billingUsageReadSequence = 0;'),end=html.indexOf('/* 复用正式订单、原价与同一权益入账链。 */',start);vm.runInContext(html.slice(start,end),c);
 const image={physical_calls:1,estimated_cost_rmb:.64,known_billed_cost_rmb:0,actual_cost_rmb:null,cost_status:'partial',unconfirmed_bills:1,calls:[{input_images:3,output_images:1,billed_images:null}]};
 const text=c.billingUsageImageCost(image);assert.match(text,/按张预计 ¥0.6400/);assert.match(text,/实际生图费用未核实/);assert.match(text,/计费 待核/);assert.doesNotMatch(text,/实际生图账单 ¥0/);
 assert.match(c.billingUsageImageCost({...image,actual_cost_rmb:.61,cost_status:'actual'}),/实际生图账单 ¥0.6100/);
 c.window={_billingUsageIdentity:{},_lastUsageData:{by_operation:{cover_generate:{label:'笔记封面',kind:'business_operation',count:1,count_basis:'usage_records',status_counts:{completed:1},known_calculated_rmb:.03,cost_complete:true,total_tokens:2000,credits_used:8,image_usage:image}},recent_records:[{operation:'cover_generate',label:'笔记封面',image_usage:image,status:'committed',credits_used:8,recorded_at:'2026-10-20T00:00:00Z'}]}};
 c.renderUsageDetail();assert.match(get('profile-usage-by-op').innerHTML,/Token计量不代表封面全部费用/);assert.match(get('profile-usage-by-op').innerHTML,/实际生图费用未核实/);assert.match(get('profile-usage-recent').innerHTML,/按张预计 ¥0.6400/);
});

test('refresh restores only the minimal original wire and explicit recovery reuses its UUID and exact payload',async()=>{
 const original=make({fetch:async()=>{throw Error('before admission');}});original.ctx.titleChoices=['已有标题'];original.el('title').value='已有标题';await original.c.coverCreate(original.ctx);
 const sent=JSON.stringify(original.ctx.pendingBody),requests=[];
 const restored=make({fetch:async(url,options={})=>{requests.push({method:options.method||'GET',body:options.body});return options.method?{ok:true,json:async()=>({...completed,request_id:JSON.parse(options.body).request_id,status:'queued',has_final:false})}:{ok:true,json:async()=>({jobs:[]})};}});
 for(const [key,value] of original.storage)restored.storage.set(key,value);
 restored.ctx.pending=restored.c.coverReadPending(restored.ctx);restored.ctx.selected.clear();restored.el('title').value='';
 assert.equal(JSON.stringify(restored.ctx.pendingBody),sent);await restored.c.coverRecoverPending(restored.ctx);
 assert.deepEqual(requests.map(row=>row.method),['GET','POST']);assert.equal(requests[1].body,sent);assert.equal(restored.storage.size,0);
 const encoded=[...original.storage.values()].join();const wire=JSON.parse(encoded);assert.deepEqual(Object.keys(wire).sort(),['quote_version','request_id','source_media_refs','title']);assert.ok(!encoded.includes('synthetic-token'));
});
test('unreadable history forbids original-wire resubmission and malformed storage never restores extra content',async()=>{
 let posts=0;const {c,ctx,storage}=make({fetch:async(url,options={})=>{if(options.method)posts++;return {ok:true,json:async()=>({jobs:[],history_unavailable:true})};}});
 ctx.pendingBody={request_id:completed.request_id,quote_version:'v',source_media_refs:['11111111-1111-4111-8111-111111111111']};c.coverWritePending(ctx,{request_id:completed.request_id,quote_version:'v'});
 await c.coverRecoverPending(ctx);assert.equal(posts,0);assert.ok(ctx.pending);assert.match(ctx.notice,/记录暂不可读/);
 assert.equal(c.coverRestorableWire({...ctx.pendingBody,token:'must-not-store'}),null);assert.equal(c.coverRestorableWire({...ctx.pendingBody,source_media_refs:['https://invalid.example/image.png']}),null);
 assert.equal(c.coverRestorableWire({...ctx.pendingBody,source_media_refs:Array(10).fill('11111111-1111-4111-8111-111111111111')}),null);
 ctx.identity.ownerId='other-owner';assert.equal(c.coverReadPending(ctx),null);assert.equal(storage.size,1);
});

test('unavailable session persistence stops a paid submission before any transport',async()=>{
 let posts=0;const {c,ctx}=make({fetch:async()=>{posts++;throw Error('must not submit');}});c.sessionStorage.setItem=()=>{throw Error('storage denied');};
 await c.coverCreate(ctx);assert.equal(posts,0);assert.equal(ctx.pending,null);assert.match(ctx.notice,/恢复状态.*本次未提交/);
});

test('saved cover settlement refreshes ledger-backed balance once per completed job',()=>{
 let reads=0;const {c,ctx}=make({refreshCreditBalance:async()=>{reads++;return {total_available_credits:0};}});
 c.coverAcceptJob(ctx,{...completed,status:'queued',has_final:false,billing:{status:'reserved',reserved_credits:8}});
 assert.equal(reads,0);
 c.coverAcceptJob(ctx,completed);assert.equal(reads,1);
 c.coverAcceptJob(ctx,completed);c.coverAcceptJob(ctx,{...completed,asset_revision:2});assert.equal(reads,1);
 c.coverAcceptJob(ctx,{...completed,job_id:'next-completed-job'});assert.equal(reads,2);
});

test('a released cover hold refreshes the ledger balance once without charging or replacing a saved cover',()=>{
 let reads=0;const {c,ctx}=make({refreshCreditBalance:async()=>{reads++;}});
 ctx.latest={...completed};
 const failed={...completed,job_id:'failed-task',status:'failed',stage:'failed',has_final:false,billing:{status:'released',credits_used:0,reserved_credits:0}};
 c.coverAcceptJob(ctx,{...failed,status:'outcome_unknown',billing:{status:'reserved',reserved_credits:8}});assert.equal(reads,0);
 c.coverAcceptJob(ctx,failed);c.coverAcceptJob(ctx,failed);
 assert.equal(reads,1);assert.equal(ctx.latest.job_id,completed.job_id);
});

test('terminal polling replaces the quote taken during a credit hold using reads only',async()=>{
 let poll,reads=0,posts=0,balanceReads=0;
 const failed={...completed,job_id:'failed-task',status:'failed',stage:'failed',has_final:false,billing:{status:'released',credits_used:0,reserved_credits:0}};
 const {c,ctx,el}=make({setTimeout:callback=>{poll=callback;return 99;},refreshCreditBalance:async()=>{balanceReads++;},fetch:async(url,options={})=>{
  if(options.method){posts++;throw Error('must only read');}
  reads++;
  return {ok:true,json:async()=>url.endsWith('/covers/failed-task')?failed:{enabled:true,quote:{operation:'cover_generate',credits:8,quote_version:'current',can_afford:true,charge_timing:'after_saved_cover'},jobs:[failed,completed],latest_success:completed}};
 }});
 ctx.latest={...completed};ctx.previewKey=completed.job_id+':'+completed.asset_revision;
 ctx.active={...failed,status:'running',stage:'design',billing:{status:'reserved',reserved_credits:8}};
 ctx.quote.can_afford=false;c.coverScheduleRead(ctx);await poll();
 assert.equal(reads,2);assert.equal(posts,0);assert.equal(balanceReads,1);
 assert.equal(el('availability').textContent,'');assert.equal(el('create').disabled,false);
 assert.match(el('status').textContent,/预留已释放，本任务不扣分/);assert.equal(ctx.latest.job_id,completed.job_id);
});

test('a failed terminal quote read cannot keep an obsolete insufficient-credit warning or enable submission',async()=>{
 let poll,posts=0;
 const failed={...completed,job_id:'failed-task',status:'failed',stage:'failed',has_final:false,billing:{status:'released',credits_used:0,reserved_credits:0}};
 const {c,ctx,el}=make({setTimeout:callback=>{poll=callback;return 99;},fetch:async(url,options={})=>{
  if(options.method){posts++;throw Error('must only read');}
  if(url.endsWith('/covers/failed-task'))return {ok:true,json:async()=>failed};
  throw Error('报价读取中断');
 }});
 ctx.active={...failed,status:'running',stage:'design',billing:{status:'reserved',reserved_credits:8}};
 ctx.quote.can_afford=false;c.coverScheduleRead(ctx);await poll();await c.coverCreate(ctx);
 assert.equal(posts,0);assert.equal(ctx.quote,null);assert.equal(el('create').disabled,true);
 assert.equal(el('availability').textContent,'');assert.match(el('quote').textContent,/报价暂不可用/);
 assert.match(el('status').textContent,/报价读取中断/);assert.match(el('status').textContent,/本任务不扣分/);
});

test('desktop cover save opens the picker before fetching and reports success only after close',{timeout:2000},async()=>{
 const events=[],blob=new Blob(['saved-cover-bytes'],{type:'image/png'});let finishClose,closeStarted,request,pickerOptions;
 const closeGate=new Promise(resolve=>finishClose=resolve),closing=new Promise(resolve=>closeStarted=resolve);
 const writable={write:async value=>{assert.equal(value,blob);events.push('write');},close:async()=>{events.push('close');closeStarted();await closeGate;},abort:async()=>events.push('abort')};
 const {c,ctx}=make({showSaveFilePicker:options=>{pickerOptions=options;events.push('picker');return Promise.resolve({createWritable:async()=>{events.push('create');return writable;}});},
  fetch:async(url,options)=>{request={url,options};events.push('fetch');return {ok:true,blob:async()=>blob};}});
 ctx.latest={...completed};ctx.notice='封面已保存到所选位置。';const saved=JSON.stringify(ctx.latest),saving=c.coverDownload(ctx);
 assert.deepEqual(events,['picker']);await c.coverDownload(ctx);assert.equal(events.filter(event=>event==='picker').length,1);
 await closing;
 assert.doesNotMatch(ctx.notice || '',/已保存/);assert.equal(ctx.busy,true);
 assert.equal(request.url,'http://offline.invalid/covers/job-original/download?asset=final&revision=1');
 assert.equal(request.options.headers.Authorization,'Bearer synthetic-token');assert.equal(request.options.cache,'no-store');
 assert.deepEqual(JSON.parse(JSON.stringify(pickerOptions)),{suggestedName:'NoteAI-cover-job-orig.png',types:[{description:'PNG 封面',accept:{'image/png':['.png']}}],excludeAcceptAllOption:true});
 finishClose();await saving;
 assert.deepEqual(events,['picker','fetch','create','write','close']);assert.match(ctx.notice,/已保存到所选位置/);
 assert.equal(ctx.busy,false);assert.equal(JSON.stringify(ctx.latest),saved);
});

test('desktop cover save cancellation never fetches or falls back to a second download',async()=>{
 let requests=0,pickers=0,anchors=0;
 const {c,ctx}=make({showSaveFilePicker:async()=>{pickers++;throw Object.assign(Error('user cancelled'),{name:'AbortError'});},
  fetch:async()=>{requests++;throw Error('cancelled picker must not fetch');},document:{createElement:()=>{anchors++;throw Error('must not fall back');}}});
 ctx.latest={...completed};await c.coverDownload(ctx);
 assert.equal(pickers,1);assert.equal(requests,0);assert.equal(anchors,0);assert.match(ctx.notice,/已取消保存/);
 assert.doesNotMatch(ctx.notice,/已保存|已交给浏览器/);assert.equal(ctx.busy,false);assert.equal(ctx.latest.asset_revision,1);
});

test('desktop cover save aborts write or close failures without retry or a success receipt',async()=>{
 for(const failure of ['write','close']) {
  let requests=0,writes=0,closes=0,aborts=0;
  const {c,ctx}=make({showSaveFilePicker:async()=>({createWritable:async()=>({
   write:async()=>{writes++;if(failure==='write')throw Error('disk write failed');},
   close:async()=>{closes++;if(failure==='close')throw Error('disk close failed');},abort:async()=>{aborts++;}
  })}),fetch:async()=>{requests++;return {ok:true,blob:async()=>new Blob(['cover'],{type:'image/png'})};}});
  ctx.latest={...completed};const saved=JSON.stringify(ctx.latest);await c.coverDownload(ctx);
  assert.equal(requests,1);assert.equal(writes,1);assert.equal(closes,failure==='close'?1:0);assert.equal(aborts,1);
  assert.match(ctx.notice,/disk (write|close) failed/);assert.doesNotMatch(ctx.notice,/已保存|已交给浏览器/);
  assert.equal(ctx.busy,false);assert.equal(JSON.stringify(ctx.latest),saved);assert.equal(ctx.urls.size,0);
 }
});

test('desktop cover save fences owner job and revision changes before writing or committing',async()=>{
 for(const stage of ['picker','fetch','blob','create','write'])for(const change of ['owner','job','revision','closed']) {
  let requests=0,writes=0,closes=0,aborts=0,ctx,leave;
  function invalidate(at){if(stage!==at)return;if(change==='owner')ctx.identity.ownerId='other-owner';else if(change==='job')ctx.latest={...completed,job_id:'other-job'};else if(change==='revision')ctx.latest={...completed,asset_revision:2};else leave();}
  const writable={write:async()=>{writes++;invalidate('write');},close:async()=>{closes++;},abort:async()=>{aborts++;}};
  const fixture=make({showSaveFilePicker:async()=>{invalidate('picker');return {createWritable:async()=>{invalidate('create');return writable;}};},
   fetch:async()=>{requests++;invalidate('fetch');return {ok:true,blob:async()=>{invalidate('blob');return new Blob(['cover'],{type:'image/png'});}};}});
  ({ctx,leave}=fixture);ctx.latest={...completed};await fixture.c.coverDownload(ctx);
  assert.equal(requests,stage==='picker'?0:1,stage+':'+change);assert.equal(writes,stage==='write'?1:0,stage+':'+change);
  assert.equal(closes,0,stage+':'+change);assert.equal(aborts,['create','write'].includes(stage)?1:0,stage+':'+change);
  assert.doesNotMatch(ctx.notice || '',/已保存|已交给浏览器/);assert.equal(ctx.busy,false);
 }
});

test('cover download retains the authenticated Blob fallback when the desktop picker is unavailable',async()=>{
 let request;const events=[],link={click(){events.push('click');},remove(){events.push('remove');}};
 const {c,ctx}=make({document:{createElement:name=>{assert.equal(name,'a');return link;},body:{append:value=>{assert.equal(value,link);events.push('append');}}},
  fetch:async(url,options)=>{request={url,options};return {ok:true,blob:async()=>new Blob(['cover'],{type:'image/png'})};}});
 ctx.latest={...completed};await c.coverDownload(ctx);
 assert.deepEqual(events,['append','click','remove']);assert.equal(link.href,'blob:synthetic');assert.equal(link.download,'NoteAI-cover-job-orig.png');
 assert.equal(request.options.headers.Authorization,'Bearer synthetic-token');assert.equal(request.url.includes('synthetic-token'),false);
 assert.match(ctx.notice,/已交给浏览器下载/);assert.doesNotMatch(ctx.notice,/已保存到所选位置/);assert.equal(ctx.latest.asset_revision,1);
});
