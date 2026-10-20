/* Real loopback API + PC/H5 UI. Cover/report APIs are never route-fulfilled. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto');
const {chromium}=require(process.env.NOTEAI_PLAYWRIGHT_MODULE || '/Users/openclaw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const output=process.env.NOTEAI_COVER_HTTP_EVIDENCE || '/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/loopback-integration';
const mode=process.env.NOTEAI_COVER_HTTP_MODE || 'legacy_v1',layered=mode==='source_photo_v2';
assert.ok(['legacy_v1','source_photo_v2'].includes(mode),'unsupported explicit cover harness mode');
const python=path.join(root,'.venv/bin/python');
const browserPath=process.env.NOTEAI_PLAYWRIGHT_EXECUTABLE || '/Users/openclaw/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
function pngDimensions(buffer){assert.equal(buffer.subarray(0,8).toString('hex'),'89504e470d0a1a0a');return [buffer.readUInt32BE(16),buffer.readUInt32BE(20)];}
async function sourcePins(){
 const names=['tests/frontend_cover_api_integration.py','tests/frontend_cover_api_integration.js','NoteAI_Pro_Demo_Framer.html','model/api.py','model/cover_jobs.py','model/cover_service.py','model/cover_runtime.py','model/cover_design.py','model/cover_renderer.py','assets/fonts/cover/MANIFEST.json'];
 return Promise.all(names.map(async name=>{const body=await fs.readFile(path.join(root,name));return {path:name,bytes:body.length,sha256:crypto.createHash('sha256').update(body).digest('hex')};}));
}
async function run(){
 await fs.mkdir(output,{recursive:true});
 const sourceFiles=await sourcePins();
 const backend=cp.spawn(python,[path.join(__dirname,'frontend_cover_api_integration.py')],{cwd:root,env:{...process.env,DATABASE_URL:'',PYTHON_DOTENV_DISABLED:'1'},stdio:['ignore','pipe','pipe']});
 let stdout='',stderr='',metadata,receipt;
 const backendExited=new Promise(resolve=>backend.once('exit',(code,signal)=>resolve({code,signal})));
 backend.stderr.on('data',data=>stderr+=data.toString());
 const ready=new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(Error('loopback readiness timeout: '+stderr)),20000);
  backend.stdout.on('data',data=>{stdout+=data.toString();for(const line of stdout.split('\n')){try{const row=JSON.parse(line);if(row.origin){clearTimeout(timer);return resolve(row);}}catch{}}});
  backend.on('exit',code=>{clearTimeout(timer);reject(Error('loopback exited '+code+': '+stderr));});
 });
 let browser,activePage,activeDiagnostics;const receipts=[];
 try{
  metadata=await ready;
  assert.equal(metadata.mode,mode);
  browser=await chromium.launch({headless:true,executablePath:browserPath});
  for(const [index,viewport] of [{width:1280,height:900},{width:390,height:844}].entries()){
   const report=metadata.reports[index],context=await browser.newContext({viewport,acceptDownloads:true,serviceWorkers:'block'}),page=await context.newPage();
   const errors=[],responses=[],requests=[],blocked=[],consoleErrors=[];
   activePage=page;activeDiagnostics={viewport,report,errors,responses,requests,blocked,consoleErrors};
   page.on('pageerror',error=>errors.push(error.message));
   page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
   page.on('response',response=>{if(response.url().startsWith(metadata.origin))responses.push({url:response.url(),status:response.status(),contentType:response.headers()['content-type'],cacheControl:response.headers()['cache-control']});});
   page.on('request',request=>{if(request.url().startsWith(metadata.origin)){const pathname=new URL(request.url()).pathname;requests.push({path:pathname,method:request.method(),...(request.method()==='POST'&&/\/reports\/[^/]+\/[^/]+\/covers$/.test(pathname)?{body:request.postDataJSON()}: {})});}});
   await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin!==metadata.origin){blocked.push(url.origin+url.pathname);return route.abort('blockedbyclient');}return route.continue();});
   await context.routeWebSocket('**/*',socket=>socket.close());
   await page.addInitScript(token=>localStorage.setItem('noteai_token',token),metadata.token);
   async function openSavedReport(){
    await page.waitForFunction(owner=>_authVerifiedOwnerId===owner,metadata.owner_id);
    if(viewport.width<900){const toggle=page.locator('#nav-menu-toggle');if(await toggle.isVisible())await toggle.click();}
    await page.locator('[data-nav-page="report"]').click();
    await page.locator(`[data-report-id="${report.report_id}"]`).waitFor({state:'visible'});
    await page.locator(`[data-report-id="${report.report_id}"]`).click();
    await page.waitForFunction(rid=>_historyReportSelection?.report_id===rid,report.report_id);
    await page.getByRole('button',{name:'一键生成笔记封面',exact:true}).click();
    await page.locator('#report-cover-panel').waitFor({state:'visible'});
   }
   await page.goto(metadata.origin+'/NoteAI_Pro_Demo_Framer.html');await openSavedReport();
   assert.ok((await page.title()).trim());assert.ok((await page.locator('body').innerText()).length>100);
   const panel=page.locator('#report-cover-panel');
   await page.waitForFunction(count=>document.querySelectorAll('[data-cover-source]:checked').length===count,metadata.source_count);
   if(layered){
    await page.waitForFunction(()=>[...document.querySelectorAll('[data-cover="sources"] img')].filter(image=>image.naturalWidth>0).length===9);
    await panel.locator('[data-cover="title"]').selectOption({label:metadata.title});
   }
   await page.waitForFunction(()=>!document.querySelector('[data-cover="create"]').disabled);
   const before=await (await fetch(metadata.origin+'/__cover_test__/state')).json();
   await panel.locator('[data-cover="create"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('等待封面制作名额'));
   const queued=await (await fetch(metadata.origin+'/__cover_test__/state')).json();
   const task=queued.jobs.find(job=>job.report_id===report.report_id);assert.ok(task);assert.equal(task.status,'queued');
   assert.equal(queued.model_calls,before.model_calls);assert.equal(queued.usage.find(row=>row.id===task.usage_id).charged_credits,0);
   const observedStates=[{job:task,statusText:await panel.locator('[data-cover="status"]').textContent(),modelCalls:queued.model_calls}];
   await panel.evaluate(el=>el.scrollTop=0);
   await page.screenshot({path:path.join(output,`cover-http-queued-${viewport.width}.png`)});
   const runningRequest=fetch(metadata.origin+'/__cover_test__/run-next',{method:'POST'});
   if(layered){
    try{
     let observed=false;
     for(let attempt=0;attempt<100;attempt++){
      const state=await (await fetch(metadata.origin+'/__cover_test__/state')).json();
      const actual=state.jobs.find(job=>job.id===task.id&&job.stage==='design');
      if(actual){observedStates.push({job:actual,modelCalls:state.model_calls});observed=true;break;}
      await new Promise(resolve=>setTimeout(resolve,50));
     }
     assert.ok(observed,'real persisted design stage was not observed');
     await panel.locator('[data-cover="refresh"]').click();
     await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('正在选图与设计'));
     observedStates.at(-1).statusText=await panel.locator('[data-cover="status"]').textContent();
     await panel.evaluate(el=>el.scrollTop=0);
     await page.screenshot({path:path.join(output,`cover-http-running-${viewport.width}.png`)});
    }finally{await fetch(metadata.origin+'/__cover_test__/release-design',{method:'POST'});}
   }
   const running=await (await runningRequest).json();
   assert.equal(running.result.job_id,task.id);assert.equal(running.result.status,'completed');assert.equal(running.result.billing.credits_used,8);
   await panel.locator('[data-cover="refresh"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth===1776);
   await panel.evaluate(el=>el.scrollTop=0);
   await page.screenshot({path:path.join(output,`cover-http-saved-${viewport.width}.png`)});
   await page.reload();await openSavedReport();
   await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth===1776);
   assert.match(await panel.locator('[data-cover="status"]').textContent(),/实际扣分 8/);
   const afterReload=await (await fetch(metadata.origin+'/__cover_test__/state')).json();
   observedStates.push({job:afterReload.jobs.find(job=>job.id===task.id),statusText:await panel.locator('[data-cover="status"]').textContent(),modelCalls:afterReload.model_calls});
   assert.equal(afterReload.model_calls,before.model_calls+2);assert.equal(afterReload.jobs.filter(job=>job.report_id===report.report_id).length,1);
   if(layered){
    const layout=afterReload.layouts[task.id];assert.equal(layout.schema_version,2);assert.equal(layout.photos.length,2);assert.equal(layout.text_layers.length,2);
    assert.deepEqual(layout.text_layers.map(layer=>layer.font_id),['SourceHanSerifSC-Regular','SourceHanSansSC-Bold']);
    assert.equal(Object.keys(layout.input_source_hashes).length,9);
    assert.equal(await panel.locator('[data-cover="text"]').inputValue(),'高楼里的\n日式庭院汤泉');
   }
   await panel.evaluate(el=>el.scrollTop=0);
   await page.screenshot({path:path.join(output,`cover-http-reopened-${viewport.width}.png`)});
   const downloadPromise=page.waitForEvent('download');await panel.locator('[data-cover="download"]').click();const download=await downloadPromise;
   const downloaded=path.join(output,`cover-http-${viewport.width}.png`);await download.saveAs(downloaded);const bytes=await fs.readFile(downloaded);
   assert.deepEqual(pngDimensions(bytes),[1776,2368]);
   if(layered)assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),afterReload.layouts[task.id].final_sha256);
   await panel.locator('[data-cover="text"]').fill(layered?'日式庭院\n汤泉':'真实素材\n免费排字');
   await panel.locator('[data-cover="adjust"]').click();await page.waitForFunction(()=>document.querySelector('[data-cover="status"]')?.textContent.includes('排字修改已保存'));
   const adjusted=await (await fetch(metadata.origin+'/__cover_test__/state')).json(),job=adjusted.jobs.find(item=>item.id===task.id),usage=adjusted.usage.find(item=>item.id===task.usage_id);
   assert.equal(job.asset_revision,2);assert.equal(usage.charged_credits,8);assert.equal(adjusted.model_calls,afterReload.model_calls);
   observedStates.push({job,statusText:await panel.locator('[data-cover="status"]').textContent(),modelCalls:adjusted.model_calls});
   if(layered){
    assert.equal(adjusted.layouts[task.id].text,'日式庭院\n汤泉');
    for(const key of ['photos','source_hashes','input_source_hashes','base_sha256'])assert.deepEqual(adjusted.layouts[task.id][key],afterReload.layouts[task.id][key]);
   }
   assert.equal(requests.filter(row=>row.method==='POST'&&row.path===`/reports/${report.report_type}/${report.report_id}/covers`).length,1);
   const finalDownloadPromise=page.waitForEvent('download');await panel.locator('[data-cover="download"]').click();const finalDownload=await finalDownloadPromise;
   const adjustedFile=path.join(output,`cover-http-adjusted-${viewport.width}.png`);await finalDownload.saveAs(adjustedFile);const adjustedBytes=await fs.readFile(adjustedFile);assert.deepEqual(pngDimensions(adjustedBytes),[1776,2368]);
   if(layered)assert.equal(crypto.createHash('sha256').update(adjustedBytes).digest('hex'),adjusted.layouts[task.id].final_sha256);
   await panel.evaluate(el=>el.scrollTop=0);assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
   await page.screenshot({path:path.join(output,`cover-http-ui-${viewport.width}.png`)});
   if(layered){
    await page.reload();await openSavedReport();
    await page.waitForFunction(()=>document.querySelector('[data-cover="final-image"]')?.naturalWidth===1776);
    assert.equal(await panel.locator('[data-cover="text"]').inputValue(),'日式庭院\n汤泉');
    await panel.evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(output,`cover-http-adjusted-reopened-${viewport.width}.png`)});
   }
   assert.deepEqual(errors,[]);assert.ok(responses.some(row=>row.url.includes('/reports/analyze/')&&row.status===200));
   assert.ok(!responses.some(row=>/\/covers(?:\/|$)|\/cover-sources(?:\/|$)/.test(row.url)&&row.status>=400));
   assert.ok(!requests.some(row=>row.method==='POST'&&/\/(generate|analyze)(?:\/|$)/.test(row.path)&&!row.path.endsWith('/covers')));
   receipts.push({viewport,url:page.url(),title:await page.title(),report_id:report.report_id,job_id:task.id,
    mode,requests,apiResponses:responses,pageErrors:errors,consoleErrors,blockedExternalResources:blocked,observedStates,
    coverPosts:1,providerPhysicalCalls:2,chargedCredits:8,assetRevision:2,downloadBytes:bytes.length,
    downloadSha256:crypto.createHash('sha256').update(bytes).digest('hex'),downloadDimensions:pngDimensions(bytes),
    adjustedDownload:{path:adjustedFile,bytes:adjustedBytes.length,sha256:crypto.createHash('sha256').update(adjustedBytes).digest('hex'),dimensions:pngDimensions(adjustedBytes)},
    ...(layered?{selectedOriginalIndices:[7,9],designSawAllNine:true,photosUnchangedByFreeEdit:true,shortenedText:'日式庭院\n汤泉',adjustedReloadRecovered:true}:{}),
    reloadRecoveredOriginal:true,freeAdjustmentNoNewProvider:true,auth:'TEST_ONLY_DEPENDENCY_OVERRIDE_NOT_REAL_LOGIN',
    api:'REAL_LOOPBACK_FASTAPI_SQLITE_PRIVATE_OBJECTS',supplier:layered?'MOCK_DESIGN_AND_QC_REAL_NINE_PHOTOS_PRODUCT_RENDERER_NOT_REAL_MODEL_QA':'MOCK_TRANSPORT_SYNTHETIC_IMAGE_NOT_REAL_MODEL_QA',realIphoneSave:false});
   await context.close();
  }
  const finalState=await (await fetch(metadata.origin+'/__cover_test__/state')).json();
  assert.equal(finalState.jobs.length,2);assert.equal(finalState.model_calls,4);assert.equal(finalState.usage.reduce((sum,row)=>sum+row.charged_credits,0),16);
  delete finalState.token;
  assert.deepEqual(await sourcePins(),sourceFiles,'source changed during browser validation');
  receipt={status:'PASS',mode,sourceFiles,Browser:'Browser plugin not available; browser skill not listed. Bundled regular Playwright with Chromium1228.',flow:layered?'saved own report → queued → running design → saved layered cover → reload reopen → free shorter copy/line breaks → actual PNG download':'saved own report → queued → saved cover → reload reopen → free text edit → actual PNG download',network:'LOOPBACK_HTTP_ONLY_SUPPLIERS_MOCKED',realModelCalls:0,lifespan:'off',receipts,finalState};
  console.log(JSON.stringify({status:'PASS',evidence:output,viewports:receipts.map(row=>row.viewport),coverJobs:2,realLocalHttp:true,realModelCalls:0}));
 }catch(error){
  const failure={status:'FAIL',mode,error:error.stack||String(error),diagnostics:activeDiagnostics};
  if(activePage&&!activePage.isClosed()){
   failure.visibleText=await activePage.locator('body').innerText().catch(()=>null);
   await activePage.screenshot({path:path.join(output,'cover-http-failure.png')}).catch(()=>{});
  }
  if(metadata){try{failure.backend=await (await fetch(metadata.origin+'/__cover_test__/state')).json();delete failure.backend.token;}catch{}}
  await fs.writeFile(path.join(output,'HTTP-BROWSER-FAILURE.json'),JSON.stringify(failure,null,2));
  throw error;
 }finally{
  if(browser)await browser.close();
  if(metadata)try{await fetch(metadata.origin+'/__cover_test__/stop',{method:'POST'});}catch{}
  let waitTimer;
  const ended=await Promise.race([backendExited,new Promise(resolve=>{waitTimer=setTimeout(()=>resolve(null),5000);})]);
  clearTimeout(waitTimer);
  if(!ended)backend.kill('SIGTERM');
  let listenerRefused=false;
  if(metadata){try{await fetch(metadata.origin+'/__cover_test__/state',{signal:AbortSignal.timeout(1000)});}catch{listenerRefused=true;}}
  if(receipt){
   const artifacts=[];
   for(const name of (await fs.readdir(output)).filter(name=>name.endsWith('.png'))){const body=await fs.readFile(path.join(output,name));artifacts.push({path:path.join(output,name),bytes:body.length,sha256:crypto.createHash('sha256').update(body).digest('hex')});}
   receipt.cleanup={browser_closed_by_playwright:true,owned_backend_process_exited:!!ended,backend_exit:ended,
    owned_loopback_origin:metadata.origin,listener_read_refused:listenerRefused,external_model_calls:0};
   receipt.artifacts=artifacts;
   await fs.writeFile(path.join(output,'HTTP-BROWSER-RECEIPT.json'),JSON.stringify(receipt,null,2));
   assert.ok(ended&&ended.code===0&&listenerRefused,'owned backend did not close cleanly');
  }
  await fs.writeFile(path.join(output,'loopback-server.log'),stderr);
 }
}
run().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
