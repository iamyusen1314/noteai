const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'NoteAI_Pro_Demo_Framer.html'), 'utf8');
const profile = html.slice(html.indexOf('let _profileReadSequence'), html.indexOf('/* 联系方式验证与账户安全 */'));
const avatars = html.slice(html.indexOf('const _AVATAR_EMOJIS'), html.indexOf('/* ═══════════════════════════════════════════════════════════\n   URL 追踪系统'));
const tracking = html.slice(html.indexOf('function profileTrackingAvailable()'), html.indexOf('\nlet _manualFillId'));
const renderAvatar = html.slice(html.indexOf('function renderAvatar('), html.indexOf('\nfunction authUpdateNav('));
class Element {
  constructor(tag = 'div') { this.tagName=tag;this.style={};this.dataset={};this.children=[];this.attributes={};this.value='';this.events={};this._text='';this._html=''; }
  set textContent(value) {this._text=String(value);this._html='';this.children=[];}
  get textContent() {return this._text+this._html.replace(/<[^>]*>/g,'')+this.children.map(c=>c.textContent).join('');}
  set innerHTML(value) {this._html=String(value);this._text='';this.children=[];}
  get innerHTML() {return this._html;}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  appendChild(node){this.append(node);return node;}
  replaceChildren(...nodes){this._text='';this._html='';this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  querySelector(selector){const key=selector.slice(1,-1).replace(/^data-/,'').replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return this.children.find(x=>Object.hasOwn(x.dataset,key))||null;}
  focus(){} select(){}
}
function response(data,status=200) {return {ok:status>=200&&status<300,status,json:async()=>data};}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function fixture(overrides={}) {
  const nodes=new Map(),get=id=>{if(!nodes.has(id)){const el=new Element();el.id=id;el.parentElement=new Element();el.nextElementSibling=new Element();el.previousElementSibling=new Element();nodes.set(id,el);}return nodes.get(id);};
  const calls=[],toasts=[];
  const data={
    '/auth/me':{id:'owner-a',username:'alpha',nickname:'Alpha',avatar_emoji:'🌸'},
    '/profile/growth':{records:[{id:'zero',score:0,score_kind:'prediction',note_id:'one',source_recorded_at:'2026-08-01',record_origin:'recoverable',persisted:false},{id:'actual',score:92,score_kind:'performance',note_id:'two'},{id:'unknown',score:null}],stats:{total_sessions:999,best_score:999,domain_distribution:{'美食':3}}},
    '/profile/memories':{memories:Array.from({length:8},(_,i)=>({id:'m'+i,user_id:'owner-a',memory_type:'style',content:'tone:自然'+i,preference_key:'tone',value:'自然'+i,editable:i===0,deletable:i===0}))},
    '/profile/achievements':{achievements:['首次评分突破50分',{name:'兼容结构成就'}]},
    '/notes?limit=3':{notes:[{id:'one',title:'合成笔记',score:0}],total:1},
    '/notes/tracking':{notes:[]},
  };
  const c=vm.createContext({console,document:{getElementById:get,createElement:tag=>new Element(tag)},_authToken:'token-a',_authUser:{id:'owner-a',username:'alpha',nickname:'Alpha'},epoch:1,API_AUTH:'https://synthetic.invalid',PUBLIC_PRODUCT:true,_publicStatus:{tracking_open:false},
    showToast:m=>toasts.push(m),authUpdateNav(){},openAuthModal(){},confirm:()=>true,escapeHtml:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),productActionAttributes:()=>'',
    fetch:async(url,options={})=>{const path=url.replace('https://synthetic.invalid','');calls.push({path,options});return overrides[path]?overrides[path](options,c):response(data[path]);},
  });
  c._chatIdentitySnapshot=()=>({ownerId:c._authUser?.id,epoch:c.epoch});c._chatIdentityMatches=s=>!!s?.ownerId&&s.ownerId===c._authUser?.id&&s.epoch===c.epoch;
  vm.runInContext(profile+'\n'+avatars+'\n'+tracking+'\n'+renderAvatar,c);
  return {c,get,data,calls,toasts,switchOwner(){c._authToken='token-b';c._authUser={id:'owner-b',username:'beta',nickname:'Beta'};c.epoch++;c.clearProfileUserState();}};
}
test('all inline scripts still parse',()=>{for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))if(m[1].trim())new vm.Script(m[1]);});
test('closed tracking is never fetched; independent real sections including zero render',async()=>{const f=fixture();await Promise.all([f.c.initProfilePage(),f.c.loadTrackingList()]);assert(!f.calls.some(r=>r.path==='/notes/tracking'));assert.equal(f.get('profile-stat-sessions').textContent,'3');assert.equal(f.get('profile-stat-improvement').textContent,'2');assert.equal(f.get('profile-stat-best').textContent,'0.0');assert.match(f.get('profile-notes-preview').innerHTML,/>0\.0</);assert.equal(f.get('profile-memories-list').children.length,8);assert.match(f.get('profile-achievements-list').textContent,/首次评分/);});
test('tracking 404 HTML does not suppress growth/memories/achievements or appear empty',async()=>{const f=fixture({'/notes/tracking':()=>({ok:false,status:404,json:async()=>{throw Error('HTML');}})});f.c._publicStatus.tracking_open=true;await Promise.all([f.c.initProfilePage(),f.c.loadTrackingList()]);assert.equal(f.get('profile-stat-best').textContent,'0.0');assert.equal(f.get('profile-memories-list').children.length,8);assert.match(f.get('profile-tracking-list').textContent,/404/);assert.match(f.get('profile-loop-insights').textContent,/读取失败/);});
for(const [path,id] of [['/profile/growth','profile-trend-chart'],['/profile/memories','profile-memories-list'],['/profile/achievements','profile-achievements-list'],['/notes?limit=3','profile-notes-preview']])test(path+' failure stays local and visible',async()=>{const f=fixture({[path]:()=>response({detail:'synthetic failure'},503)});await f.c.initProfilePage();assert.match(f.get(id).textContent,/503/);assert.equal(f.get('profile-nickname-display').textContent,'Alpha');if(path!=='/profile/growth')assert.equal(f.get('profile-stat-best').textContent,'0.0');if(path!=='/profile/memories')assert.equal(f.get('profile-memories-list').children.length,8);});
test('invalid JSON and missing array are errors, not zero/empty',async()=>{const f=fixture({'/profile/growth':()=>({ok:true,status:200,json:async()=>{throw Error('HTML');}}),'/profile/memories':()=>response({})});await f.c.initProfilePage();assert.match(f.get('profile-trend-chart').textContent,/无法读取/);assert.match(f.get('profile-memories-list').textContent,/格式不完整/);assert.equal(f.get('profile-stat-sessions').textContent,'–');});
test('separate prediction/performance plots never join unrelated notes; provenance is visible',async()=>{const f=fixture();await f.c.initProfilePage();const chart=f.get('profile-trend-chart').innerHTML;assert(!chart.includes('<path'));assert.match(chart,/预测评分/);assert.match(chart,/发布后实际表现/);assert.match(chart,/尚未归档/);assert.match(chart,/2026-08-01/);assert(!f.get('profile-loop-insights').textContent.includes('+92'));});
test('null and legacy score types remain unknown while legacy numeric zero displays',()=>{const f=fixture();f.c.renderProfileGrowth({records:[{score:0,id:'old'},{score:null}],stats:{}});assert.equal(f.get('profile-stat-best').textContent,'0.0');assert.equal(f.get('profile-stat-improvement').textContent,'1');assert.match(f.get('profile-trend-chart').innerHTML,/类型未记录/);});
test('late profile data cannot overwrite another account',async()=>{const late=deferred();const f=fixture({'/auth/me':()=>late.promise});const run=f.c.initProfilePage();await Promise.resolve();f.switchOwner();f.get('profile-nickname-display').textContent='Beta';late.resolve(response({id:'owner-a',username:'alpha',nickname:'Alpha'}));await run;assert.equal(f.get('profile-nickname-display').textContent,'Beta');assert.equal(f.c._authUser.id,'owner-b');assert.equal(f.get('profile-memories-list').children.length,0);});
test('latest same-account read wins',async()=>{const late=deferred();let n=0;const f=fixture({'/profile/growth':()=>++n===1?late.promise:response({records:[{score:10}],stats:{}})});const old=f.c.initProfilePage();await f.c.initProfilePage();late.resolve(response({records:[{score:99}],stats:{}}));await old;assert.equal(f.get('profile-stat-best').textContent,'10.0');});
test('memory text is safe; only explicit editable own preference has controls',async()=>{const f=fixture();f.data['/profile/memories'].memories.push({id:'ctx',memory_type:'context',content:'<img onerror=bad>',editable:true,preference_key:'tone'});await f.c.initProfilePage();const list=f.get('profile-memories-list');assert.equal(list.children.length,9);assert.equal(list.children[8].children[1].textContent,'<img onerror=bad>');assert(!list.children[8].children.some(x=>x.children.some(y=>y.dataset.profileMemoryEdit)));assert.equal(await f.c.changeProfileMemory('ctx','value'),false);assert.equal(await f.c.changeProfileMemory('m7','value'),false);});
test('memory edit submits raw value and refreshes real returned list',async()=>{let changed=false;const f=fixture({'/profile/memories/m0':options=>{assert.equal(options.method,'PATCH');assert.deepEqual(JSON.parse(options.body),{value:'简洁'});changed=true;return response({ok:true});},'/profile/memories':()=>response({memories:[{id:'m0',memory_type:'style',preference_key:'tone',value:changed?'简洁':'自然',content:'tone:'+(changed?'简洁':'自然'),editable:true}]})});await f.c.initProfilePage();assert.equal(await f.c.changeProfileMemory('m0',' 简洁 '),true);assert.match(f.get('profile-memories-list').textContent,/简洁/);});
test('memory deletion requires success and never rewrites history payload',async()=>{const f=fixture({'/profile/memories/m0':options=>{assert.equal(options.method,'DELETE');assert.equal(options.body,undefined);return response({ok:true});}});await f.c.initProfilePage();assert.equal(await f.c.changeProfileMemory('m0',null),true);assert.equal(f.calls.filter(r=>r.options.method==='DELETE').length,1);});
test('HTTP failure with body ok cannot falsely confirm memory or account save',async()=>{const f=fixture({'/profile/memories/m0':()=>response({ok:true},500),'/auth/profile':()=>response({ok:true,nickname:'Wrong'},500)});await f.c.initProfilePage();assert.equal(await f.c.changeProfileMemory('m0','new'),false);f.c.startNicknameEdit();f.get('profile-nickname-input').value='New';assert.equal(await f.c.saveNickname(),false);assert.equal(f.c._authUser.nickname,'Alpha');assert(!f.toasts.some(t=>t.includes('已更新')));});
test('nickname save requires body.ok and successful response updates canonical nickname',async()=>{let ok=false;const f=fixture({'/auth/profile':options=>{assert.equal(options.method,'PUT');assert.equal(JSON.parse(options.body).nickname,'New');return response({ok,nickname:'Canonical'});}});await f.c.initProfilePage();f.c.startNicknameEdit();f.get('profile-nickname-input').value='New';assert.equal(await f.c.saveNickname(),false);ok=true;assert.equal(await f.c.saveNickname(),true);assert.equal(f.c._authUser.nickname,'Canonical');assert.equal(f.get('profile-nickname-display').textContent,'Canonical');});
test('late nickname/emoji save cannot update switched account',async()=>{for(const kind of ['nickname','emoji']){const late=deferred();const f=fixture({'/auth/profile':()=>late.promise});await f.c.initProfilePage();let save;if(kind==='nickname'){f.c.startNicknameEdit();f.get('profile-nickname-input').value='New';save=f.c.saveNickname();}else save=f.c.pickAvatar('⭐');f.switchOwner();f.get('profile-nickname-display').textContent='Beta';late.resolve(response({ok:true,nickname:'New',avatar_emoji:'⭐'}));assert.equal(await save,false);assert.equal(f.c._authUser.nickname,'Beta');assert.equal(f.get('profile-nickname-display').textContent,'Beta');}});
test('avatar upload keeps original size restriction and ignores late compression after logout',async()=>{const f=fixture();await f.c.processAvatarFile({type:'image/png',size:11*1024*1024});assert.match(f.toasts.at(-1),/10MB/);const late=deferred();f.c.compressImageToSquare=()=>late.promise;const run=f.c.processAvatarFile({type:'image/png',size:10});f.switchOwner();late.resolve('data:image/jpeg;base64,QQ==');await run;assert.equal(await f.c.saveUploadedAvatar(),false);assert(!f.calls.some(r=>r.path==='/auth/profile'));});
test('same-owner avatar upload saves its captured data and checks HTTP success',async()=>{const f=fixture({'/auth/profile':options=>{assert.deepEqual(JSON.parse(options.body),{avatar_data:'data:image/jpeg;base64,QQ=='});return response({ok:true,avatar_data:'data:image/jpeg;base64,QQ=='});}});f.c.compressImageToSquare=async()=> 'data:image/jpeg;base64,QQ==';await f.c.processAvatarFile({type:'image/png',size:10});assert.equal(await f.c.saveUploadedAvatar(),true);assert.equal(f.c._authUser.avatar_data,'data:image/jpeg;base64,QQ==');});

test('legacy preference summaries have no invented ID or mutation buttons',async()=>{const f=fixture();f.data['/profile/memories']={memories:[],preferences:[{preference_key:'tone',value:'自然',content:'语气：自然',domain:null,source:'legacy_user_learn',editable:false,deletable:false,updated_at:'2026-09-18'}]};await f.c.initProfilePage();const list=f.get('profile-memories-list');assert.equal(list.children.length,1);assert.match(list.textContent,/语气：自然/);assert(!list.children[0].children.some(e=>e.tagName==='button'));assert.match(f.get('profile-loop-insights').textContent,/1 项偏好/);assert.equal(await f.c.changeProfileMemory('tone','修改'),false);});
test('editable does not grant delete permission',async()=>{const f=fixture();f.data['/profile/memories'].memories[0].deletable=false;await f.c.initProfilePage();assert.equal(await f.c.changeProfileMemory('m0',null),false);assert(!f.calls.some(r=>r.options.method==='DELETE'));});
test('explicit foreign-owner memories are rejected before rendering',async()=>{const f=fixture();f.data['/profile/memories'].memories[0].user_id='other';await f.c.initProfilePage();assert.match(f.get('profile-memories-list').textContent,/账户不匹配/);assert(!f.get('profile-memories-list').children.some(e=>e.dataset.profileMemoryId));assert(!f.get('profile-memories-list').textContent.includes('自然'));assert.equal(f.get('profile-memories-list').children[0].textContent,'重新读取');});

test('a region retry rereads only that region and clears its failure',async()=>{let fails=true;const f=fixture({'/profile/memories':()=>fails?response({},503):response({memories:[]})});await f.c.initProfilePage();const count=f.calls.length;fails=false;await f.get('profile-memories-list').children[0].events.click();assert.deepEqual(f.calls.slice(count).map(x=>x.path),['/profile/memories']);assert(!f.get('profile-memories-list').textContent.includes('503'));});
test('read-only tracking flag permits history while create remains closed',async()=>{const f=fixture();f.c._publicStatus.tracking_read_open=true;await f.c.loadTrackingList();assert(f.calls.some(x=>x.path==='/notes/tracking'));assert.equal(f.c._publicStatus.tracking_open,false);});
test('profile read started before successful nickname save cannot restore old fields',async()=>{const late=deferred();let delay=false;const f=fixture({'/auth/me':()=>delay?late.promise:response({id:'owner-a',username:'alpha',nickname:'Alpha'}),'/auth/profile':()=>response({ok:true,nickname:'New'})});await f.c.initProfilePage();delay=true;const read=f.c.initProfilePage();f.c.startNicknameEdit();f.get('profile-nickname-input').value='New';assert.equal(await f.c.saveNickname(),true);late.resolve(response({id:'owner-a',username:'alpha',nickname:'Alpha'}));await read;assert.equal(f.c._authUser.nickname,'New');assert.equal(f.get('profile-nickname-display').textContent,'New');assert.equal(f.get('profile-memories-list').children.length,8);});

test('growth report navigation uses the exact returned reference and rejects invented links',async()=>{const f=fixture();const routes=[],reads=[];f.c.showPage=p=>routes.push(p);f.c.openReportDetail=(kind,id)=>reads.push([kind,id]);f.data['/profile/growth'].records[0].report_ref={report_type:'analyze',report_id:'original-report'};await f.c.initProfilePage();await f.c.openProfileReport('generate','original-report');assert.equal(reads.length,0);await f.c.openProfileReport('analyze','original-report');assert.deepEqual(routes,['report']);assert.deepEqual(reads,[['analyze','original-report']]);f.switchOwner();await f.c.openProfileReport('analyze','original-report');assert.equal(reads.length,1);});

test('uncertain preference save retains editor draft and blocks duplicate mutation until readback',async()=>{const f=fixture({'/profile/memories/m0':()=>response({ok:true},503)});await f.c.initProfilePage();const row=f.get('profile-memories-list').children[0];f.c.openProfileMemoryEditor('m0',row);const input=row.querySelector('[data-profile-memory-value]');input.value='保留草稿';assert.equal(await f.c.changeProfileMemory('m0',input.value),false);assert.equal(input.value,'保留草稿');assert(f.get('profile-memories-list').children.includes(row));assert.equal(await f.c.changeProfileMemory('m0',input.value),false);assert.equal(f.calls.filter(x=>x.options.method==='PATCH').length,1);const notice=f.get('profile-memories-list').querySelector('[data-profile-memory-recheck]');await notice.children[1].events.click();assert.equal(f.get('profile-memories-list').children.length,8);});

// Real auth restore + real profile functions, with independently controlled response order.
function installProfileAuthRestore(f, {active = true, guest = true} = {}) {
  const start=html.indexOf('async function authRestoreSession() {');
  const source=html.slice(start,html.indexOf('\n}',start)+2);
  const resumed=[];let pageActive=active;
  f.get('page-profile').classList={contains:name=>name==='active'&&pageActive};
  if(guest)f.c._authUser=null;
  f.c._authVerifiedOwnerId=null;
  Object.defineProperty(f.c,'_chatUserStateEpoch',{get:()=>f.c.epoch,set:value=>{f.c.epoch=value;}});
  f.c._chatOwnerId=(user=f.c._authUser)=>user?.id==null?null:String(user.id);
  f.c.chatClearUserState=()=>{f.c.epoch++;f.c.clearProfileUserState();};
  f.c.authClearLocalSession=()=>{f.c._authToken=null;f.c._authUser=null;f.c._authVerifiedOwnerId=null;f.c.chatClearUserState();};
  f.c.loadBillingPlan=()=>{};f.c.chatRestoreSession=()=>{};f.c.restorePendingTaskClarification=()=>{};f.c.offerMediaRecovery=()=>{};
  for(const name of ['initProfilePage','loadTrackingList']){const original=f.c[name];f.c[name]=(...args)=>{const run=original(...args);resumed.push(run);return run;};}
  vm.runInContext(source,f.c);
  return {resumed,leave:()=>{pageActive=false;},settle:()=>Promise.all(resumed)};
}
test('early profile and tracking recover after same-token owner restoration completes',async()=>{
  const auth=deferred();let reads=0;
  const f=fixture({'/auth/me':()=>++reads===1?auth.promise:response({id:'owner-a',username:'alpha',nickname:'Alpha'})});
  const run=installProfileAuthRestore(f);f.c._publicStatus.tracking_read_open=true;
  const restoring=f.c.authRestoreSession();await Promise.all([f.c.initProfilePage(),f.c.loadTrackingList()]);
  assert.equal(f.c._authUser,null);assert.equal(f.get('profile-stat-sessions').textContent,'–');assert.match(f.get('profile-memories-list').textContent,/正在读取/);
  auth.resolve(response({id:'owner-a',username:'alpha',nickname:'Alpha'}));assert.equal(await restoring,true);await run.settle();
  assert.equal(f.c._authVerifiedOwnerId,'owner-a');assert.equal(f.get('profile-stat-sessions').textContent,'3');assert.equal(f.get('profile-stat-best').textContent,'0.0');
  assert.equal(f.get('profile-memories-list').children.length,8);assert.match(f.get('profile-achievements-list').textContent,/首次评分/);assert.match(f.get('profile-tracking-list').textContent,/暂无已有追踪记录/);
});
test('empty-owner data arriving after restored profile cannot overwrite fresh reads',async()=>{
  const auth=deferred(),oldGrowth=deferred();let reads=0,growthReads=0;
  const f=fixture({'/auth/me':()=>++reads===1?auth.promise:response({id:'owner-a',username:'alpha',nickname:'Alpha'}),'/profile/growth':()=>++growthReads===1?oldGrowth.promise:response({records:[{score:0,score_kind:'prediction',note_id:'current'}],stats:{}})});
  const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();const early=f.c.initProfilePage();
  auth.resolve(response({id:'owner-a',username:'alpha',nickname:'Alpha'}));assert.equal(await restoring,true);
  await Promise.all(run.resumed.slice(1));assert.equal(f.get('profile-stat-best').textContent,'0.0');
  oldGrowth.resolve(response({records:[{score:99,score_kind:'prediction',note_id:'old'}],stats:{}}));await early;
  assert.equal(f.get('profile-stat-best').textContent,'0.0');assert.doesNotMatch(f.get('profile-trend-chart').innerHTML,/99\.0/);
});
test('restoration after leaving profile does not start background profile reads',async()=>{
  const auth=deferred();const f=fixture({'/auth/me':()=>auth.promise});const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();run.leave();
  auth.resolve(response({id:'owner-a',username:'alpha'}));assert.equal(await restoring,true);assert.equal(run.resumed.length,0);assert.deepEqual(f.calls.map(c=>c.path),['/auth/me']);
});
test('restoring an existing owner does not discard an active preference editor',async()=>{
  const f=fixture();await f.c.initProfilePage();const row=f.get('profile-memories-list').children[0];f.c.openProfileMemoryEditor('m0',row);const input=row.querySelector('[data-profile-memory-value]');input.value='尚未保存的草稿';
  const run=installProfileAuthRestore(f,{guest:false});assert.equal(await f.c.authRestoreSession(),true);assert.equal(run.resumed.length,0);assert.equal(input.value,'尚未保存的草稿');assert(f.get('profile-memories-list').children.includes(row));
});
test('old restore cannot resume profile after account or token changes',async()=>{
  const auth=deferred();const f=fixture({'/auth/me':()=>auth.promise});const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();f.switchOwner();
  auth.resolve(response({id:'owner-a',username:'alpha'}));assert.equal(await restoring,false);assert.equal(f.c._authUser.id,'owner-b');assert.equal(run.resumed.length,0);
});
for(const failure of [false,true])test('same token reintroduced after clear still rejects old-epoch restore '+(failure?'failure':'success'),async()=>{
  const auth=deferred();const f=fixture({'/auth/me':()=>auth.promise});const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();
  f.c.authClearLocalSession();f.c._authToken='token-a';f.c._authUser={id:'owner-b',username:'beta',nickname:'Beta'};
  auth.resolve(failure?{ok:true,status:200,json:async()=>{throw Error('old response JSON failed');}}:response({id:'owner-a',username:'alpha'}));
  assert.equal(await restoring,false);assert.equal(f.c._authToken,'token-a');assert.equal(f.c._authUser.id,'owner-b');assert.equal(run.resumed.length,0);
});
test('identity epoch changed while auth JSON is pending cannot resume or overwrite profile',async()=>{
  const body=deferred(),parsing=deferred();const f=fixture({'/auth/me':()=>({ok:true,status:200,json:()=>{parsing.resolve();return body.promise;}})});
  const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();await parsing.promise;
  f.c.authClearLocalSession();f.c._authToken='token-a';f.c._authUser={id:'owner-b',username:'beta'};body.resolve({id:'owner-a',username:'alpha'});
  assert.equal(await restoring,false);assert.equal(f.c._authUser.id,'owner-b');assert.equal(run.resumed.length,0);
});
test('failed authentication never resumes private profile reads or accepts stale data',async()=>{
  const f=fixture({'/auth/me':()=>response({},401)});const run=installProfileAuthRestore(f);assert.equal(await f.c.authRestoreSession(),false);
  assert.equal(f.c._authToken,null);assert.equal(f.c._authUser,null);assert.equal(f.calls.length,1);assert.equal(f.get('profile-real-content').style.display,'none');assert.equal(f.get('profile-login-prompt').style.display,'flex');
});

for(const [label,reply] of [['missing owner',()=>response({username:'invalid'})],['network failure',()=>{throw Error('offline');}]])test('early profile authentication '+label+' returns to original login prompt',async()=>{
  const f=fixture({'/auth/me':reply});const run=installProfileAuthRestore(f);f.get('profile-login-prompt').style.display='none';f.get('profile-real-content').style.display='block';
  assert.equal(await f.c.authRestoreSession(),false);await run.settle();
  assert.equal(f.get('profile-real-content').style.display,'none');assert.equal(f.get('profile-login-prompt').style.display,'flex');assert.equal(f.c._authToken,null);assert.equal(f.calls.length,1);
});
test('failed restore after leaving profile does not alter its login visibility',async()=>{
  const auth=deferred(),f=fixture({'/auth/me':()=>auth.promise});const run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();run.leave();f.get('profile-login-prompt').style.display='none';
  auth.resolve(response({},401));assert.equal(await restoring,false);assert.equal(run.resumed.length,0);assert.equal(f.get('profile-login-prompt').style.display,'none');
});
test('old-epoch network rejection cannot clear a reintroduced same-token session',async()=>{
  let reject;const pending=new Promise((_,fail)=>{reject=fail;});const f=fixture({'/auth/me':()=>pending}),run=installProfileAuthRestore(f),restoring=f.c.authRestoreSession();
  f.c.authClearLocalSession();f.c._authToken='token-a';f.c._authUser={id:'owner-b',username:'beta'};reject(Error('old network failure'));
  assert.equal(await restoring,false);assert.equal(f.c._authToken,'token-a');assert.equal(f.c._authUser.id,'owner-b');assert.equal(run.resumed.length,0);
});
