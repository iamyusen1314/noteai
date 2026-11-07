/* Offline PC/H5 cover interaction proof. No API/model/production transport. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),http=require('node:http');
const {chromium}=require(process.env.NOTEAI_PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'..');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64');
const quote={operation:'cover_generate',credits:8,quote_version:'synthetic-cover-v1',can_afford:true,charge_timing:'after_saved_cover'};
const readySources=count=>Array.from({length:count},(_,i)=>({media_ref:`${String(i+1).padStart(8,'0')}-1111-4111-8111-111111111111`,status:'ready',expires_at:'2026-10-21T00:00:00Z',content_type:'image/png'}));
function savedVersionReport(type) {
 const note={id:'55555555-5555-4555-8555-555555555555',title:'真实素材合成验证',body:'仅供离线交互验证，不是真实供应商成品。',version:1};
 return {report_type:type,report_id:'synthetic-saved-report',saved_note_id:note.id,result:{note_title:note.title,note_body:note.body,saved_note_id:note.id,note_version_group:{versions:[note],latest:note}}};
}
async function showReport(page,type='generate') {
 await page.evaluate(async type=>{
  _authUser={id:'synthetic-cover-owner',username:'cover-test'};_authToken='synthetic-cover-token';_authVerifiedOwnerId=_authUser.id;
  document.querySelectorAll('.page').forEach(el=>el.classList.remove('active'));document.getElementById('page-report').classList.add('active');
  document.getElementById('diag-detail-section').style.display='block';
  const data={note_title:'真实素材合成验证',note_body:'仅供离线交互验证，不是真实供应商成品。',domain:'休闲娱乐体验',expert_opinions:[{role:type==='generate'?'视觉分析师':'视觉专家',opinion:'结合真实素材完整主体和标题留白设计。',suggestions:['保留主体，不编造设施或价格。']}]};
  _historyReportSelection={report_type:type,report_id:'synthetic-saved-report',result:data};
  if(type==='generate')await populateGenerateReport();
  else {document.getElementById('genReportBody').style.display='none';document.getElementById('diagReportBody').style.display='block';renderAgentResults(data.expert_opinions,'');}
 },type);
}
test('saved-report covers: PC/H5 entries, nine-source selection, reopen, free adjustment, download and safe unknown handling',{timeout:90000},async()=>{
 const server=http.createServer(async(req,res)=>{
  const name=new URL(req.url,'http://local').pathname;
  if(name==='/favicon.ico'){res.writeHead(204);return res.end();}
  if(!['/NoteAI_Pro_Demo_Framer.html','/assets/vendor/echarts-5.4.3.min.js','/assets/vendor/lucide-1.27.0.min.js','/assets/vendor/qrcode-generator-2.0.4.js','/assets/vendor/three.module.min.js','/assets/payment-native.js','/assets/landing/v04-quality-engine.png'].includes(name)){res.writeHead(404);return res.end();}
  try {const data=await fs.readFile(path.join(root,name));res.writeHead(200,{'Content-Type':name.endsWith('.html')?'text/html':name.endsWith('.png')?'image/png':'application/javascript'});res.end(data);}catch{res.writeHead(404);res.end();}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 let browser;try {browser=await chromium.launch({headless:true,...(process.env.NOTEAI_PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.NOTEAI_PLAYWRIGHT_EXECUTABLE}:{})});}catch(error){await new Promise(r=>server.close(r));throw error;}const receipts=[];
 try {
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]) {
   const context=await browser.newContext({viewport,acceptDownloads:true,serviceWorkers:'block'});
   // This scenario verifies the authenticated Blob fallback; picker save is covered separately.
   await context.addInitScript(()=>Object.defineProperty(globalThis,'showSaveFilePicker',{configurable:true,value:undefined}));
   const page=await context.newPage();
   const calls=[],consoleErrors=[],pageErrors=[],failedResources=[];let sources=readySources(9),job=null,enabled=true,unknownPost=false,source404=false,deliveredJob=null,rejectMode='';
   page.on('response',response=>{if(response.status()>=400)failedResources.push({url:response.url(),status:response.status()});});
   page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});page.on('pageerror',error=>pageErrors.push(error.message));
   await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin!==origin)return route.abort('blockedbyclient');
    if(url.pathname==='/runtime-config.js')return route.fulfill({contentType:'application/javascript',body:`window.NOTEAI_API_BASE=${JSON.stringify(origin+'/synthetic-api')};`});
    if(!url.pathname.startsWith('/synthetic-api/'))return route.continue();
    const p=url.pathname.replace('/synthetic-api',''),method=req.method();calls.push({p,method,authorization:req.headers().authorization||'',body:req.postData()});
    const send=data=>route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    const report=/^\/reports\/(generate|analyze)\/synthetic-saved-report$/.exec(p);
    if(report&&method==='GET')return send(savedVersionReport(report[1]));
    if(p.endsWith('/cover-sources')&&method==='GET'&&source404)return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({detail:'原报告已到期'})});
    if(p==='/covers'&&method==='GET')return send({jobs:job?.status==='completed'?[job]:[]});
    if(p.endsWith('/cover-sources')&&method==='GET')return send({status:sources.length?'ready':'reupload_required',sources,ready_count:sources.length});
    if(/\/cover-sources\/[^/]+$/.test(p))return route.fulfill({contentType:'image/png',body:png});
    if(p.endsWith('/cover-sources')&&method==='PUT'){sources=JSON.parse(req.postData()).media_refs.map(media_ref=>({media_ref,status:'ready'}));return send({status:'ready',sources,ready_count:sources.length});}
    if(p==='/upload-image')return send({media_ref:'22222222-2222-4222-8222-222222222222'});
    if(p.endsWith('/covers')&&method==='GET')return send({enabled,reason:enabled?'':'暂时关闭新提交',quote:enabled?quote:null,jobs:job?[job]:[],latest_success:job?.status==='completed'?job:null});
    if(p.endsWith('/covers')&&method==='POST'){
     const body=JSON.parse(req.postData());
     if(rejectMode)return route.fulfill({status:rejectMode==='quote'?409:402,contentType:'application/json',body:JSON.stringify({detail:{code:rejectMode==='quote'?'BILLING_QUOTE_CHANGED':'QUOTA_EXCEEDED',message:'明确未受理',admitted:false,reserved_credits:0}})});
     if(unknownPost==='before_admission'){unknownPost=false;return route.abort('connectionclosed');}
     job={job_id:'33333333-3333-4333-8333-333333333333',request_id:body.request_id,report_type:'generate',report_id:'synthetic-saved-report',status:'queued',stage:'queued',created_at:'2026-10-20T00:00:00Z',expires_at:'2027-01-18T00:00:00Z',has_final:false,asset_revision:1,layout:{text:'真实素材\n封面验证',position:'top',position_options:['bottom']},billing:{status:'reserved',reserved_credits:8,credits_used:0}};
     if(unknownPost)return route.abort('connectionclosed');return send(job);
    }
    if(p.endsWith('/adjust')){const body=JSON.parse(req.postData());assert.equal(body.expected_revision,job.asset_revision);job={...job,asset_revision:job.asset_revision+1,layout:{...job.layout,text:body.text,position:body.position || job.layout.position}};return send(job);}
    if(p.endsWith('/download'))return route.fulfill({contentType:'image/png',headers:{'Content-Disposition':'attachment; filename="cover.png"'},body:png});
    if(p.startsWith('/covers/'))return send(job);
    if(p==='/billing/plan')return send({total_available_credits:100});
    if(p==='/public/status')return send({image_open:true,ai_open:true});
    if(p==='/auth/me')return send({user:{id:'synthetic-cover-owner',username:'cover-test'}});
    return send({});
   });
   await context.routeWebSocket('**/*',socket=>socket.close());
   await page.goto(origin+'/NoteAI_Pro_Demo_Framer.html');
   assert.ok((await page.title()).includes('NoteAI'));await showReport(page);
   await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();
   const panel=page.locator('#report-cover-panel');await panel.waitFor({state:'visible'});
   await page.waitForFunction(()=>document.querySelectorAll('[data-cover-source]:checked').length===9);
   assert.match(await panel.locator('[data-cover="quote"]').textContent(),/8 积分/);
   await panel.locator('[data-cover="title"]').selectOption({label:'真实素材合成验证'});
   await panel.locator('[data-cover="create"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('等待封面制作名额'));
   assert.equal(calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length,1);
   await panel.locator('[data-cover="close"]').click();assert.equal(await page.locator('#report-cover-panel').count(),0);
   job={...job,status:'completed',stage:'completed',has_final:true,billing:{status:'committed',credits_used:8,reserved_credits:0}};
   await page.reload();await showReport(page);await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth>0);
   assert.equal(calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length,1);
   assert.match(await panel.locator('[data-cover="status"]').textContent(),/实际扣分 8/);
   assert.deepEqual(await panel.locator('[data-cover="position"] option').evaluateAll(options=>options.map(option=>option.value)),['','bottom']);
   await panel.locator('[data-cover="text"]').fill('免费改字\n保留主体');await panel.locator('[data-cover="position"]').selectOption('bottom');
   await panel.locator('[data-cover="adjust"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('排字修改已保存'));
   assert.equal(job.asset_revision,2);deliveredJob={...job};assert.equal(job.layout.position,'bottom');assert.equal(job.layout.text,'免费改字\n保留主体');
   const downloadPromise=page.waitForEvent('download');await panel.locator('[data-cover="download"]').click();const download=await downloadPromise;assert.match(download.suggestedFilename(),/^NoteAI-cover-/);
   if(process.env.NOTEAI_COVER_UI_EVIDENCE){await fs.mkdir(process.env.NOTEAI_COVER_UI_EVIDENCE,{recursive:true});await download.saveAs(path.join(process.env.NOTEAI_COVER_UI_EVIDENCE,`download-${viewport.width}.png`));await panel.evaluate(el=>el.scrollTop=0);assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1));await page.screenshot({path:path.join(process.env.NOTEAI_COVER_UI_EVIDENCE,`cover-${viewport.width}.png`)});}
   await panel.locator('[data-cover="close"]').click();enabled=false;
   await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-cover="availability"]')?.textContent.includes('暂时关闭'));
   assert.equal(await panel.locator('[data-cover="create"]').isDisabled(),true);assert.equal(await panel.locator('[data-cover="download"]').isEnabled(),true);await panel.locator('[data-cover="close"]').click();
   enabled=true;job=null;sources=[];await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-cover="source-note"]')?.textContent.includes('原图缺失'));
   assert.equal(await panel.locator('[data-cover="create"]').isDisabled(),true);
   await panel.locator('[data-cover="file"]').setInputFiles({name:'synthetic-source.png',mimeType:'image/png',buffer:png});
   await page.waitForFunction(()=>document.querySelectorAll('[data-cover-source]:checked').length===1);
   assert.ok(calls.some(call=>call.method==='PUT'&&call.p.endsWith('/cover-sources')));
   for(const rejection of ['quote','balance']) {
    rejectMode=rejection;await panel.locator('[data-cover="create"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('未受理、未预留'));
    assert.equal(await panel.locator('[data-cover="recover"]').isVisible(),false);
    assert.equal(await page.evaluate(()=>_coverPanel.pending),null);
    rejectMode='';await panel.locator('[data-cover="refresh"]').click();
    await page.waitForFunction(()=>!document.querySelector('[data-cover="create"]').disabled);
   }
   unknownPost='before_admission';job=null;await panel.locator('[data-cover="create"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('受理结果待核查'));
   const pendingWireBeforeReload=await page.evaluate(()=>JSON.stringify(_coverPanel.pendingBody));
   await page.reload();await showReport(page);await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="recover"]')?.hidden===false);
   assert.equal(await page.evaluate(()=>JSON.stringify(_coverPanel.pendingBody)),pendingWireBeforeReload);
   await panel.locator('[data-cover="recover"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('原编号与原内容已确认'));
   const replayBodies=calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).slice(-2).map(call=>call.body);assert.equal(replayBodies[0],replayBodies[1]);
   job={...job,status:'failed',stage:'failed',billing:{status:'released',credits_used:0,reserved_credits:0}};await panel.locator('[data-cover="refresh"]').click();
   await page.waitForFunction(()=>!document.querySelector('[data-cover="create"]').disabled);
   unknownPost=true;await panel.locator('[data-cover="create"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('受理结果待核查'));
   const posts=calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length;
   await panel.locator('[data-cover="recover"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('已找回原请求'));
   assert.equal(calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length,posts);
   await panel.locator('[data-cover="close"]').click();
   // The report's seven-day retention may end before this cover's 90-day deadline.
   enabled=false;source404=true;job=deliveredJob;await showReport(page);
   await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth>0);
   await page.waitForFunction(()=>document.querySelector('[data-cover="source-note"]')?.textContent.includes('已有封面仍可'));
   assert.equal(await panel.locator('[data-cover="download"]').isEnabled(),true);await panel.locator('[data-cover="close"]').click();
   const sourceReadsBeforeSaved=calls.filter(call=>call.p.includes('/cover-sources')).length;
   await page.evaluate(()=>{_historyReportSelection=null;_generateResult=null;_diagnoseResult=null;});
   await page.getByRole('button',{name:'已保存封面',exact:true}).click();
   await page.locator('#saved-covers-panel').getByRole('button',{name:/免费改字.*保留主体/}).click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth>0);
   assert.equal(await panel.locator('[data-cover="source-form"]').isVisible(),false);
   assert.equal(await panel.locator('[data-cover="download"]').isEnabled(),true);
   assert.equal(await panel.locator('[data-cover="adjust"]').isEnabled(),true);
   assert.equal(calls.filter(call=>call.p.includes('/cover-sources')).length,sourceReadsBeforeSaved);
   assert.equal(calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length,posts);
   await panel.locator('[data-cover="text"]').fill('原报告到期\n仍可免费排字');
   await panel.locator('[data-cover="adjust"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('排字修改已保存'));
   assert.equal(job.asset_revision,3);assert.equal(job.billing.credits_used,8);
   const expiredDownloadPromise=page.waitForEvent('download');await panel.locator('[data-cover="download"]').click();await expiredDownloadPromise;
   assert.equal(calls.filter(call=>call.p.includes('/cover-sources')).length,sourceReadsBeforeSaved);
   assert.equal(calls.filter(call=>call.method==='POST'&&call.p.endsWith('/covers')).length,posts);
   if(process.env.NOTEAI_COVER_UI_EVIDENCE)await page.screenshot({path:path.join(process.env.NOTEAI_COVER_UI_EVIDENCE,`saved-cover-after-report-expiry-${viewport.width}.png`)});
   await panel.locator('[data-cover="close"]').click();source404=false;await showReport(page,'analyze');
   await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();await panel.waitFor({state:'visible'});
   await panel.locator('[data-cover="close"]').click();
   await page.evaluate(()=>{
    document.querySelectorAll('.page').forEach(el=>el.classList.remove('active'));document.getElementById('page-profile').classList.add('active');
    const image={physical_calls:1,estimated_cost_rmb:.64,known_billed_cost_rmb:0,actual_cost_rmb:null,cost_status:'partial',unconfirmed_bills:1,calls:[{input_images:3,output_images:1,billed_images:null}]};
    window._billingUsageIdentity=_chatIdentitySnapshot();window._lastUsageData={by_operation:{cover_generate:{label:'笔记封面',kind:'business_operation',count:1,count_basis:'usage_records',status_counts:{completed:1},known_calculated_rmb:.03,cost_complete:true,total_tokens:2000,credits_used:8,image_usage:image}},recent_records:[{operation:'cover_generate',label:'笔记封面',image_usage:image,status:'committed',credits_used:8,recorded_at:'2026-10-20T00:00:00Z'}]};
    document.getElementById('profile-usage-detail').style.display='block';renderUsageDetail();
   });
   assert.match(await page.locator('#profile-usage-by-op').textContent(),/Token计量不代表封面全部费用/);
   assert.match(await page.locator('#profile-usage-recent').textContent(),/按张预计 ¥0.6400.*实际生图费用未核实/);
   await page.evaluate(()=>{authClearLocalSession();});assert.equal(await page.locator('#report-cover-panel').count(),0);
   const coverCalls=calls.filter(call=>call.p.includes('/covers')||call.p.includes('/cover-sources')||call.p==='/upload-image');assert.ok(coverCalls.every(call=>call.authorization==='Bearer synthetic-cover-token'));assert.ok(coverCalls.every(call=>!call.p.includes('token=')));
   assert.deepEqual(pageErrors,[]);
   receipts.push({viewport,url:page.url(),title:await page.title(),pageErrors,consoleErrors,failedResources,sourceInspections:calls.filter(c=>c.p.endsWith('/cover-sources')&&c.method==='GET').length,coverPosts:posts,adjustPosts:calls.filter(c=>c.p.endsWith('/adjust')).length,downloaded:true,accountCleanup:true,expiredReportReopen:true,savedCoverDoesNotReadSources:true,structuredUnheldRejections:true,sameIdExplicitRecovery:true,refreshOriginalWireRecovery:true,safePositionChoices:true,imageUsageCostStatus:true,api:'MOCK_ONLY',realIphoneSave:false});
   await context.close();
  }
 } finally {await browser.close();await new Promise(r=>server.close(r));}
 if(process.env.NOTEAI_COVER_UI_EVIDENCE)await fs.writeFile(path.join(process.env.NOTEAI_COVER_UI_EVIDENCE,'browser-receipt.json'),JSON.stringify({status:'PASS',Browser:'Browser plugin not available; bundled regular Playwright',network:'LOOPBACK_STATIC_AND_SYNTHETIC_API_ONLY',realModelCalls:0,receipts},null,2));
});
test('truthful cover progress cards retain six steps, distinguish confirmation delays and restore one GET on PC/H5',{timeout:60000},async()=>{
 const server=http.createServer(async(req,res)=>{
  const name=new URL(req.url,'http://local').pathname;
  if(name==='/favicon.ico'){res.writeHead(204);return res.end();}
  if(!['/NoteAI_Pro_Demo_Framer.html','/assets/vendor/echarts-5.4.3.min.js','/assets/vendor/lucide-1.27.0.min.js','/assets/vendor/qrcode-generator-2.0.4.js','/assets/vendor/three.module.min.js','/assets/payment-native.js','/assets/landing/v04-quality-engine.png'].includes(name)){res.writeHead(404);return res.end();}
  try{const body=await fs.readFile(path.join(root,name));res.writeHead(200,{'Content-Type':name.endsWith('.html')?'text/html':name.endsWith('.png')?'image/png':'application/javascript'});res.end(body);}catch{res.writeHead(404);res.end();}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 let browser;const receipts=[],output=process.env.NOTEAI_COVER_UI_EVIDENCE;
 try{
  browser=await chromium.launch({headless:true,...(process.env.NOTEAI_PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.NOTEAI_PLAYWRIGHT_EXECUTABLE}:{})});
  if(output)await fs.mkdir(output,{recursive:true});
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
   const context=await browser.newContext({viewport,serviceWorkers:'block'}),page=await context.newPage(),requests=[],pageErrors=[];
   page.on('pageerror',error=>pageErrors.push(error.message));
   const now=Date.now(),iso=offset=>new Date(now+offset).toISOString();
   let outage=false,job={job_id:'33333333-3333-4333-8333-333333333333',request_id:'44444444-4444-4444-8444-444444444444',report_type:'generate',report_id:'synthetic-saved-report',status:'queued',stage:'queued',created_at:iso(-120000),server_time:iso(0),has_final:false,asset_revision:0,billing:{status:'reserved',reserved_credits:8,credits_used:0},progress:{schema_version:1,phase:'queued',detail_code:'waiting_slot',execution_started_at:null,phase_started_at:iso(-120000),last_worker_seen_at:null,revision:0}};
   await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());if(url.origin!==origin)return route.abort('blockedbyclient');
    if(url.pathname==='/runtime-config.js')return route.fulfill({contentType:'application/javascript',body:`window.NOTEAI_API_BASE=${JSON.stringify(origin+'/synthetic-api')};`});
    if(!url.pathname.startsWith('/synthetic-api/'))return route.continue();
    const pathname=url.pathname.replace('/synthetic-api','');requests.push({path:pathname,method:req.method()});
    const send=value=>route.fulfill({contentType:'application/json',body:JSON.stringify(value)});
    const report=/^\/reports\/(generate|analyze)\/synthetic-saved-report$/.exec(pathname);
    if(report&&req.method()==='GET')return send(savedVersionReport(report[1]));
    if(pathname==='/covers/'+job.job_id){
     if(outage)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'受控查询断线'})});
     return send(job);
    }
    if(pathname.endsWith('/covers'))return send({enabled:true,quote,jobs:[job],latest_success:null});
    if(pathname.endsWith('/cover-sources'))return send({status:'ready',sources:readySources(9),ready_count:9});
    if(/\/cover-sources\/[^/]+$/.test(pathname))return route.fulfill({contentType:'image/png',body:png});
    if(pathname==='/billing/plan')return send({total_available_credits:100});
    if(pathname==='/public/status')return send({image_open:true,ai_open:true});
    if(pathname==='/auth/me')return send({user:{id:'synthetic-cover-owner',username:'cover-test'}});
    return send({});
   });
   await context.routeWebSocket('**/*',socket=>socket.close());await page.goto(origin+'/NoteAI_Pro_Demo_Framer.html');await showReport(page);
   await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();const panel=page.locator('#report-cover-panel');
   await page.waitForFunction(()=>document.querySelector('[data-cover="progress-count"]')?.textContent.includes('排队中'));
   await page.waitForFunction(()=>_coverPanel.noteVersionsLoading===false);
   assert.match(await panel.locator('[data-cover="version-note"]').textContent(),/使用已保存的 v1/);
   assert.equal(await panel.locator('[aria-current="step"]').count(),0);assert.match(await panel.locator('[data-cover="progress-total"]').textContent(),/已排队：2分/);
   const phaseNames=['source_check','design','concept','layout','qc','saving'],details=['inspecting_sources','planning','generating_reference','rendering','adjusting','storing'];
   for(const [index,phase]of phaseNames.entries()){
    job={...job,status:'running',stage:phase==='qc'?'design':phase,server_time:iso(0),progress:{schema_version:1,phase,detail_code:details[index],execution_started_at:iso(-360000),phase_started_at:iso(-30000),last_worker_seen_at:iso(-10000),revision:phase==='qc'?1:0}};
    await panel.locator('[data-cover="refresh"]').click();await page.waitForFunction(step=>document.querySelector('[data-cover="progress-count"]')?.textContent===`第${step}/6步`,index+1);
    assert.equal(await panel.locator('[aria-current="step"]').getAttribute('data-cover-step'),String(index+1));
   }
   job={...job,stage:'design',progress:{...job.progress,phase:'qc',detail_code:'adjusting',last_worker_seen_at:iso(-100000),revision:1}};
   await panel.locator('[data-cover="refresh"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="progress-worker"]')?.textContent.includes('后台确认已延迟'));
   assert.match(await panel.locator('[data-cover="progress-count"]').textContent(),/上次确认.*第5\/6步/);
   assert.match(await panel.locator('[data-cover="progress-detail"]').textContent(),/质检意见.*局部调整/);
   assert.match(await panel.locator('[data-cover="progress-long"]').textContent(),/上次确认工作.*收起面板.*合格成品保存后结算一次/);
   assert.equal(await panel.locator('[data-cover="progress-read"]').isVisible(),false);
   assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
   if(output){await panel.evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(output,`progress-six-steps-${viewport.width}.png`)});}
   const visibility=async value=>page.evaluate(value=>{Object.defineProperty(document,'visibilityState',{configurable:true,value});document.dispatchEvent(new Event('visibilitychange'));},value);
   await visibility('hidden');outage=true;await visibility('visible');
   await page.waitForFunction(()=>document.querySelector('[data-cover="progress-read"]')?.hidden===false);
   assert.match(await panel.locator('[data-cover="progress-read"]').textContent(),/查询暂时中断.*最后取得/);
   assert.match(await panel.locator('[data-cover="progress-worker"]').textContent(),/后台确认已延迟/);
   assert.equal(await panel.locator('[data-cover="create"]').isDisabled(),true);
   if(output){await panel.evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(output,`progress-query-offline-${viewport.width}.png`)});}
   await visibility('hidden');outage=false;job={...job,status:'outcome_unknown',stage:'outcome_unknown',unknown_at:iso(0)};
   const originalReads=requests.filter(row=>row.path==='/covers/'+job.job_id).length;await visibility('visible');
   await page.waitForFunction(()=>document.querySelector('[data-cover="progress-count"]')?.textContent==='结果待核查');
   assert.equal(requests.filter(row=>row.path==='/covers/'+job.job_id).length,originalReads+1);
   assert.match(await panel.locator('[data-cover="progress-detail"]').textContent(),/原任务.*不会自动.*重发/);
   assert.equal(await panel.locator('[data-cover="progress-read"]').isVisible(),false);assert.equal(await page.evaluate(()=>_coverPanel.elapsedTimer),null);
   await panel.locator('[data-cover="close"]').click();const closedReads=requests.length;await visibility('hidden');await visibility('visible');
   assert.equal(requests.length,closedReads);assert.equal(await page.locator('#report-cover-panel').count(),0);assert.equal(requests.filter(row=>row.method==='POST').length,0);assert.deepEqual(pageErrors,[]);
   receipts.push({viewport,title:await page.title(),sixPhases:true,queueSeparate:true,qcCorrectionStep5:true,workerDelaySeparateFromReadOutage:true,visibilityOriginalGetOnly:true,unknownNoPaidResubmit:true,closeCleanup:true,coverPosts:0,pageErrors,API:'MOCK_ONLY',realModelCalls:0,visibility:'CONTROLLED_DOCUMENT_EVENT',realIphoneSave:false});
   await context.close();
  }
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
 if(output)await fs.writeFile(path.join(output,'progress-browser-receipt.json'),JSON.stringify({status:'PASS',network:'LOOPBACK_STATIC_AND_SYNTHETIC_API_ONLY',realModelCalls:0,receipts},null,2));
});
