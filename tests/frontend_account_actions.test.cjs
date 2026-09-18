const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Always exercise the delivered HTML, never a separate draft snippet.
const html = fs.readFileSync(path.join(__dirname, '..', 'NoteAI_Pro_Demo_Framer.html'), 'utf8');
function extract(name) {
  const match = new RegExp('^(?:async )?function ' + name + '\\(', 'm').exec(html);
  assert.ok(match, 'Actual HTML must define ' + name);
  const end = html.indexOf('\n}', match.index);
  assert.ok(end > match.index, 'Actual HTML function boundary: ' + name);
  return html.slice(match.index, end + 2);
}
const source = ['accountActionStart', 'accountActionJSON', 'deleteDiagnosis', 'revokeAllSessions', 'exportAccountData', 'recoverArchivedContent'].map(extract).join('\n');
const goodExport = {contract_version:'synthetic-v1',exported_at:'2026-09-19T01:00:00Z',account:{username:'synthetic-a'},archives:{notes:[],diagnoses:[]}};
function response(data, status = 200) { return {ok:status >= 200 && status < 300,status,json:async () => data}; }
function htmlResponse(status = 404) { return {ok:status >= 200 && status < 300,status,json:async () => { throw Error('Unexpected token <'); }}; }
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise,resolve}; }
function fixture(options = {}) {
  const calls = [], toasts = [], prompts = [], confirms = [], downloads = [], blobs = [], revoked = [], pages = [];
  const nodes = new Map([['diag-history-list', {innerHTML:'existing history'}]]);
  const counts = {logout:0,closeDetail:0,history:0,profile:0,removed:0};
  const data = {
    '/auth/sessions/revoke-all':{ok:true},
    '/account/export':goodExport,
    '/account/archive/recovery':{items:[{content_type:'note',content_id:'note-a',label:'合成笔记'},{content_type:'diagnosis',content_id:'diag-a',label:'合成诊断'}]},
    '/account/archive/recover':{ok:true,retention:{state:'active'}},
    '/diagnoses/diag-a':{ok:true},
  };
  const c = vm.createContext({console,Blob,Map,API_AUTH:'https://synthetic.invalid',PUBLIC_PRODUCT:true,_authToken:'synthetic-token-a',_authUser:{id:'owner-a'},epoch:1,_currentDiagId:'diag-a',_diagHistoryOffset:9,
    document:{body:{appendChild(){}},getElementById:id=>nodes.get(id),createElement:tag=>({tag,href:'',download:'',click(){if(options.click)options.click(c);downloads.push({href:this.href,filename:this.download});},remove(){counts.removed++;}})},
    URL:{createObjectURL(blob){blobs.push(blob);if(options.createObjectURL)options.createObjectURL(c);return 'blob:synthetic-' + blobs.length;},revokeObjectURL:url=>revoked.push(url)},
    fetch:async (url, init={})=>{const route=url.replace('https://synthetic.invalid','');calls.push({route,init});return options.routes?.[route]?options.routes[route](init,c):response(data[route]);},
    showToast:message=>toasts.push(message),showPage:page=>pages.push(page),
    confirm:message=>{confirms.push(message);return options.confirm?options.confirm(c):true;},
    prompt:message=>{prompts.push(message);return options.prompt?options.prompt(c):'1';},
    authClearLocalSession(){counts.logout++;c._authToken=null;c._authUser=null;c.epoch++;},
    closeDiagDetail(){counts.closeDetail++;c._currentDiagId=null;},
    async loadDiagnosisHistory(reset){counts.history++;assert.equal(reset,true);if(options.history)await options.history(c);},
    async initProfilePage(){counts.profile++;if(options.profile)await options.profile(c);},
  });
  c._chatIdentitySnapshot=()=>({ownerId:c._authUser?.id || null,epoch:c.epoch});
  c._chatIdentityMatches=snapshot=>Boolean(snapshot?.ownerId && snapshot.ownerId===c._authUser?.id && snapshot.epoch===c.epoch);
  const switchAccount=()=>{c._authUser={id:'owner-b'};c._authToken='synthetic-token-b';c.epoch++;};
  vm.runInContext(source,c);
  return {c,calls,toasts,prompts,confirms,downloads,blobs,revoked,pages,nodes,counts,switchAccount};
}

test('public session revocation retains confirmation and requires server acknowledgement before logout',async()=>{
  const f=fixture();await f.c.revokeAllSessions();
  assert.equal(f.confirms.length,1);assert.equal(f.calls[0].route,'/auth/sessions/revoke-all');assert.equal(f.calls[0].init.method,'POST');
  assert.equal(f.calls[0].init.headers.Authorization,'Bearer synthetic-token-a');assert.equal(f.counts.logout,1);assert.deepEqual(f.pages,['landing']);
});
for(const [label,result] of [['ok false',response({ok:false})],['HTTP rejection',response({ok:true,detail:'拒绝'},403)],['HTML failure',htmlResponse(502)],['malformed success',htmlResponse(200)]]) {
  test('session revocation rejects '+label+' without clearing local login',async()=>{
    const f=fixture({routes:{'/auth/sessions/revoke-all':()=>result}});await f.c.revokeAllSessions();
    assert.equal(f.calls.length,1);assert.equal(f.counts.logout,0);assert.match(f.toasts.at(-1),/未确认|失败/);assert.match(f.toasts.at(-1),/不会自动重试/);
  });
}
test('session revocation cancellation sends no request',async()=>{
  const f=fixture({confirm:()=>false});await f.c.revokeAllSessions();assert.equal(f.calls.length,0);
});
test('identity changed during confirmation cannot dispatch using another account',async()=>{
  const f=fixture({confirm:c=>{c._authToken='changed-token';return true;}});await f.c.revokeAllSessions();assert.equal(f.calls.length,0);
});
test('old-account revoke response cannot log out the newly selected account',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/sessions/revoke-all':()=>gate.promise}});const pending=f.c.revokeAllSessions();f.switchAccount();gate.resolve(response({ok:true}));await pending;
  assert.equal(f.counts.logout,0);assert.equal(f.c._authUser.id,'owner-b');assert.equal(f.toasts.length,0);
});
test('identity is checked after asynchronous revoke response JSON too',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/sessions/revoke-all':()=>({ok:true,status:200,json:()=>gate.promise})}});const pending=f.c.revokeAllSessions();await Promise.resolve();await Promise.resolve();f.switchAccount();gate.resolve({ok:true});await pending;
  assert.equal(f.counts.logout,0);assert.equal(f.toasts.length,0);
});
test('duplicate in-flight revocation sends exactly one request',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/sessions/revoke-all':()=>gate.promise}});const pending=f.c.revokeAllSessions();await f.c.revokeAllSessions();assert.equal(f.calls.length,1);gate.resolve(response({ok:true}));await pending;
});
test('unknown revoke outcome does not retry or claim success',async()=>{
  const f=fixture({routes:{'/auth/sessions/revoke-all':()=>{throw Error('network lost');}}});await f.c.revokeAllSessions();assert.equal(f.calls.length,1);assert.equal(f.counts.logout,0);assert.match(f.toasts.at(-1),/结果未确认/);
});
test('export accepts actual contract without ok or account.id, no-store and scoped bearer',async()=>{
  const f=fixture();await f.c.exportAccountData();
  assert.equal(f.calls[0].init.cache,'no-store');assert.equal(f.calls[0].init.headers.Authorization,'Bearer synthetic-token-a');
  assert.equal(f.downloads.length,1);assert.equal(f.downloads[0].filename,'noteai-account-export.json');assert.deepEqual(JSON.parse(await f.blobs[0].text()),goodExport);assert.equal(f.revoked.length,1);assert.equal(f.counts.removed,1);
});
for(const [label,result] of [['HTML success',htmlResponse(200)],['missing export contract',response({ok:true})],['HTTP rejection',response(goodExport,403)]]) {
  test('export rejects '+label+' without a download',async()=>{
    const f=fixture({routes:{'/account/export':()=>result}});await f.c.exportAccountData();assert.equal(f.downloads.length,0);assert.equal(f.blobs.length,0);assert.match(f.toasts.at(-1),/导出失败/);
  });
}
test('export discarded after account switches during fetch',async()=>{
  const gate=deferred(),f=fixture({routes:{'/account/export':()=>gate.promise}});const pending=f.c.exportAccountData();f.switchAccount();gate.resolve(response(goodExport));await pending;
  assert.equal(f.downloads.length,0);assert.equal(f.blobs.length,0);assert.equal(f.toasts.length,0);
});
test('export discarded after account switches during JSON parsing',async()=>{
  const gate=deferred(),f=fixture({routes:{'/account/export':()=>({ok:true,status:200,json:()=>gate.promise})}});const pending=f.c.exportAccountData();await Promise.resolve();await Promise.resolve();f.switchAccount();gate.resolve(goodExport);await pending;
  assert.equal(f.downloads.length,0);assert.equal(f.blobs.length,0);assert.equal(f.toasts.length,0);
});
test('export rechecks identity immediately before download and releases URL',async()=>{
  const f=fixture({createObjectURL:c=>{c._authToken='new-session';}});await f.c.exportAccountData();assert.equal(f.downloads.length,0);assert.equal(f.revoked.length,1);
});
test('failed download always releases object URL and allows a later user action',async()=>{
  let fail=true;const f=fixture({click:()=>{if(fail)throw Error('download blocked');}});await f.c.exportAccountData();assert.equal(f.revoked.length,1);fail=false;await f.c.exportAccountData();assert.equal(f.calls.length,2);assert.equal(f.downloads.length,1);assert.equal(f.revoked.length,2);
});
test('empty recovery list is a valid empty state with no write',async()=>{
  const f=fixture({routes:{'/account/archive/recovery':()=>response({items:[]})}});await f.c.recoverArchivedContent();assert.equal(f.calls.length,1);assert.equal(f.prompts.length,0);assert.match(f.toasts.at(-1),/当前没有/);
});
for(const [label,result] of [['missing items',response({})],['invalid item',response({items:[{content_type:'account',content_id:'a'}]})],['HTML 404',htmlResponse(404)]]) {
  test('recovery '+label+' is visibly failed, never rendered as empty',async()=>{
    const f=fixture({routes:{'/account/archive/recovery':()=>result}});await f.c.recoverArchivedContent();assert.equal(f.calls.length,1);assert.equal(f.prompts.length,0);assert.match(f.toasts.at(-1),/读取恢复列表失败/);assert.doesNotMatch(f.toasts.at(-1),/当前没有/);
  });
}
test('archive recovery retains ordinal prompt and submits only selected type and id',async()=>{
  const f=fixture({prompt:()=> '2'});await f.c.recoverArchivedContent();assert.equal(f.prompts.length,1);assert.equal(f.calls.length,2);
  assert.equal(f.calls[1].route,'/account/archive/recover');assert.equal(f.calls[1].init.method,'POST');assert.deepEqual(JSON.parse(f.calls[1].init.body),{content_type:'diagnosis',content_id:'diag-a'});assert.equal(f.counts.profile,1);assert.match(f.toasts.at(-1),/归档已恢复/);
});
test('archive recovery prompt cancellation performs no write',async()=>{
  const f=fixture({prompt:()=>null});await f.c.recoverArchivedContent();assert.equal(f.calls.length,1);assert.equal(f.counts.profile,0);
});
test('old-account recovery list is discarded before prompting',async()=>{
  const gate=deferred(),f=fixture({routes:{'/account/archive/recovery':()=>gate.promise}});const pending=f.c.recoverArchivedContent();f.switchAccount();gate.resolve(response({items:[{content_type:'note',content_id:'a'}]}));await pending;
  assert.equal(f.calls.length,1);assert.equal(f.prompts.length,0);assert.equal(f.toasts.length,0);
});
test('identity changed inside recovery prompt sends no write',async()=>{
  const f=fixture({prompt:c=>{c._authToken='other-session';return '1';}});await f.c.recoverArchivedContent();assert.equal(f.calls.length,1);
});
test('old-account recovery acknowledgement cannot refresh new-account profile',async()=>{
  const gate=deferred(),f=fixture({routes:{'/account/archive/recover':()=>gate.promise}});const pending=f.c.recoverArchivedContent();while(f.calls.length<2)await Promise.resolve();f.switchAccount();gate.resolve(response({ok:true}));await pending;
  assert.equal(f.counts.profile,0);assert.equal(f.toasts.length,0);
});
test('archive HTTP 200 ok:false is not successful recovery',async()=>{
  const f=fixture({routes:{'/account/archive/recover':()=>response({ok:false})}});await f.c.recoverArchivedContent();assert.equal(f.counts.profile,0);assert.match(f.toasts.at(-1),/未确认|失败/);
});
test('unknown archive recovery is never automatically retried',async()=>{
  const f=fixture({routes:{'/account/archive/recover':()=>{throw Error('network lost');}}});await f.c.recoverArchivedContent();assert.equal(f.calls.filter(c=>c.init.method==='POST').length,1);assert.equal(f.counts.profile,0);assert.match(f.toasts.at(-1),/结果未确认/);
});
test('confirmed archive recovery remains confirmed if profile refresh fails',async()=>{
  const f=fixture({profile:()=>{throw Error('refresh failed');}});await f.c.recoverArchivedContent();assert.match(f.toasts.at(-1),/归档已恢复，页面刷新失败/);
});
test('diagnosis deletion confirms, validates response and refreshes original history',async()=>{
  const f=fixture();await f.c.deleteDiagnosis('diag-a');assert.equal(f.confirms.length,1);assert.equal(f.calls[0].init.method,'DELETE');assert.equal(f.counts.closeDetail,1);assert.equal(f.counts.history,1);assert.equal(f.c._diagHistoryOffset,0);assert.equal(f.nodes.get('diag-history-list').innerHTML,'');
});
for(const [label,result] of [['HTTP rejection',response({ok:true},403)],['ok false',response({ok:false})],['HTML response',htmlResponse(502)]]) {
  test('diagnosis delete '+label+' preserves existing report and shows failure',async()=>{
    const f=fixture({routes:{'/diagnoses/diag-a':()=>result}});await f.c.deleteDiagnosis('diag-a');assert.equal(f.counts.closeDetail,0);assert.equal(f.counts.history,0);assert.equal(f.nodes.get('diag-history-list').innerHTML,'existing history');assert.match(f.toasts.at(-1),/失败|未确认/);
  });
}
test('successful deletion does not close a different report opened while waiting',async()=>{
  const gate=deferred(),f=fixture({routes:{'/diagnoses/diag-a':()=>gate.promise}});const pending=f.c.deleteDiagnosis('diag-a');f.c._currentDiagId='diag-b';gate.resolve(response({ok:true}));await pending;assert.equal(f.counts.closeDetail,0);assert.equal(f.counts.history,1);
});
test('late old-account diagnosis delete cannot clear or reload new-account report',async()=>{
  const gate=deferred(),f=fixture({routes:{'/diagnoses/diag-a':()=>gate.promise}});const pending=f.c.deleteDiagnosis('diag-a');f.switchAccount();gate.resolve(response({ok:true}));await pending;assert.equal(f.counts.closeDetail,0);assert.equal(f.counts.history,0);assert.equal(f.toasts.length,0);
});
test('unknown diagnosis deletion never retries or discards local record',async()=>{
  const f=fixture({routes:{'/diagnoses/diag-a':()=>{throw Error('network lost');}}});await f.c.deleteDiagnosis('diag-a');assert.equal(f.calls.length,1);assert.equal(f.counts.closeDetail,0);assert.equal(f.counts.history,0);assert.match(f.toasts.at(-1),/结果未确认/);
});
test('confirmed deletion is not reported as failed when history refresh fails',async()=>{
  const f=fixture({history:()=>{throw Error('refresh failed');}});await f.c.deleteDiagnosis('diag-a');assert.match(f.toasts.at(-1),/记录已删除，列表刷新失败/);
});
test('unauthenticated actions cannot invoke any private endpoint',async()=>{
  const f=fixture();f.c._authUser=null;f.c._authToken=null;
  await f.c.exportAccountData();await f.c.recoverArchivedContent();await f.c.revokeAllSessions();await f.c.deleteDiagnosis('diag-a');assert.equal(f.calls.length,0);assert.equal(f.toasts.length,4);
});
