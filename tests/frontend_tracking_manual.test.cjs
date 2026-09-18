const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Only application functions are loaded. All accounts, IDs, DOM and responses below are synthetic.
const html = fs.readFileSync(path.join(__dirname, '..', 'NoteAI_Pro_Demo_Framer.html'), 'utf8');
const sourceCache = new Map();
function source(name) {
  if (sourceCache.has(name)) return sourceCache.get(name);
  const start = html.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, 'Actual HTML function exists: ' + name);
  for (let end = html.indexOf('\n', start); end >= 0; end = html.indexOf('\n', end + 1)) {
    const candidate = html.slice(start, end);
    try { new vm.Script(candidate); sourceCache.set(name, candidate); return candidate; } catch { /* Incomplete declaration. */ }
  }
  assert.fail('Cannot extract function ' + name);
}
function trackingSource() {
  const marker = html.indexOf('URL 追踪系统 — 前端');
  assert.ok(marker >= 0);
  const start = html.indexOf('*/', marker) + 2;
  const endMarker = html.indexOf('计费系统 — 前端', start);
  const end = html.lastIndexOf('/*', endMarker);
  assert.ok(end > start);
  return html.slice(start, end);
}

const OWNER_A = '11111111-1111-4111-8111-111111111111';
const OWNER_B = '22222222-2222-4222-8222-222222222222';
const NOTE_A = '33333333-3333-4333-8333-333333333333';
const NOTE_B = '44444444-4444-4444-8444-444444444444';
const TRACK_A = '55555555-5555-4555-8555-555555555555';
const TRACK_B = '66666666-6666-4666-8666-666666666666';
const URL_A = 'https://www.xiaohongshu.com/explore/abcdef0123456789abcdef01';
const URL_B = 'https://www.xiaohongshu.com/explore/abcdef0123456789abcdef02';
const API = 'https://synthetic.invalid';
const plain = value => JSON.parse(JSON.stringify(value));
function response(data, status = 200) { return {ok:status >= 200 && status < 300, status, json:async () => data}; }
function deferred() { let resolve, reject; const promise = new Promise((a, b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; }
async function flush() { await new Promise(resolve => setImmediate(resolve)); }
const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

class Element {
  constructor(tag='div', owner) {
    this.tagName=tag.toUpperCase();this.owner=owner;this.style={};this.dataset={};this.attributes={};this.children=[];this.events={};
    this.value='';this.disabled=false;this.hidden=false;this._text='';this._html='';this._id='';this.className='';this.options=[];
    const classes=new Set();this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,on)=>{if(on)classes.add(x);else classes.delete(x);}};
  }
  set id(id) {this._id=id;if(id)this.owner?.nodes.set(id,this);}
  get id() {return this._id;}
  set textContent(value) {this._text=String(value ?? '');this._html='';this.children=[];}
  get textContent() {return this._text+this._html.replace(/<[^>]*>/g,'')+this.children.map(c=>c.textContent ?? String(c)).join('');}
  set innerHTML(value) {this._html=String(value);this._text='';this.children=[];}
  get innerHTML() {return this._html;}
  append(...nodes) {for(const node of nodes){if(typeof node==='object')node.parentElement=this;this.children.push(node);}}
  appendChild(node) {this.append(node);return node;}
  prepend(...nodes) {for(const node of nodes)node.parentElement=this;this.children.unshift(...nodes);}
  replaceChildren(...nodes) {this.textContent='';this.append(...nodes);}
  setAttribute(key,value) {this.attributes[key]=String(value);if(key==='id')this.id=value;if(key.startsWith('data-'))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=String(value);}
  getAttribute(key) {return this.attributes[key] ?? null;}
  removeAttribute(key) {delete this.attributes[key];}
  addEventListener(kind,callback) {this.events[kind]=callback;}
  focus() {if(this.owner)this.owner.activeElement=this;}
  scrollIntoView() {}
  remove() {if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.removed=true;}
  contains(node) {return this===node || this.children.some(c=>typeof c==='object'&&c.contains(node));}
  matches(selector) {
    if(selector.startsWith('#'))return this.id===selector.slice(1);
    const attr=selector.match(/^\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
    if(attr)return this.getAttribute(attr[1])!==null&&(attr[2]===undefined||this.getAttribute(attr[1])===attr[2]);
    return this.tagName===selector.toUpperCase();
  }
  querySelectorAll(selector) {return this.children.flatMap(c=>typeof c==='object'?[...(c.matches(selector)?[c]:[]),...c.querySelectorAll(selector)]:[]);}
  querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
  closest(selector) {return this.matches(selector)?this:this.parentElement?.closest(selector) || null;}
}

function row(overrides={}) {
  return {id:TRACK_A,user_id:OWNER_A,status:'needs_manual',note_title:'合成已保存笔记',domain:'美食',
    source_note_id:NOTE_A,source_root_note_id:NOTE_A,xhs_url:URL_A,submitted_at:'2026-09-19T00:00:00Z',
    next_check_at:null,provider_attempt_state:null,predicted_ces:0,actual_ces:null,evidence_source:'manual',confidence_label:'',...overrides};
}
function fixture(options={}) {
  const doc={nodes:new Map(),events:{},activeElement:null};
  const get=id=>{if(!doc.nodes.has(id)){const element=new Element('div',doc);element.id=id;}return doc.nodes.get(id);};
  doc.getElementById=get;doc.createElement=tag=>new Element(tag,doc);doc.createTextNode=text=>({textContent:String(text)});
  doc.body=new Element('body',doc);doc.addEventListener=(kind,fn)=>{doc.events[kind]=fn;};
  doc.querySelector=selector=>selector.startsWith('#')?get(selector.slice(1)):null;
  doc.querySelectorAll=selector=>Array.from(doc.nodes.values()).filter(node=>node.matches(selector));
  get('track-url-modal').style.display='none';get('track-url-domain').value='美食';
  const calls=[],toasts=[],routes=[],prompts=[],promptDefaults=[],confirmations=[],libraryReads=[];
  const answers=[...(options.answers || [])], rows=[...(options.rows || [row()])];
  const c=vm.createContext({console,URL,Map,Set,document:doc,API_AUTH:API,API_BASE:API,PUBLIC_PRODUCT:true,
    _authToken:'synthetic-token-a',_authUser:{id:OWNER_A},_authVerifiedOwnerId:OWNER_A,_chatUserStateEpoch:1,
    _publicStatus:{tracking_open:false,tracking_read_open:true,tracking_manual_open:true,tracking_delete_open:true,...options.capabilities},
    _profileTrackingReadSequence:0,_profileViewState:null,_libraryOffset:0,_libraryTotal:0,_chatSessionId:'unrelated-chat-session',_noteDetailData:null,
    _libraryReadSequence:0,_libraryIdentity:{identity:{ownerId:OWNER_A,epoch:1},token:'synthetic-token-a'},
    _librarySelectableNotes:new Map([[NOTE_A,{id:NOTE_A,title:'合成已保存笔记',domain:'美食',score:0,version:1}]]),
    _trackingBySourceNote:new Map(),_trackingByRootNote:new Map(),_trackingReadSequence:0,_trackingIndexSequence:0,_trackingIndexReadSequence:0,
    setTimeout:fn=>{fn();return 1;},clearTimeout(){},escapeHtml:escape,
    showToast:message=>toasts.push(String(message)),showPage:name=>routes.push(name),openAuthModal:mode=>routes.push('auth:'+mode),
    prompt:(message,initial)=>{prompts.push(message);promptDefaults.push(initial);return answers.length?answers.shift():null;},confirm:message=>{confirmations.push(message);return options.confirm!==false;},
    productActionAttributes:(name,...args)=>`data-product-action="${name}" data-product-args="${escape(JSON.stringify(args))}"`,
    renderProfileLoopInsights(){},loadLibrary:async reset=>libraryReads.push(reset),closeNoteDetail(){},
  });
  c.fetch=async (url,request={})=>{
    assert.ok(String(url).startsWith(API+'/'),'No external network: '+url);
    const entry={path:String(url).slice(API.length),method:request.method || 'GET',request};calls.push(entry);
    if(options.respond){const result=await options.respond(entry,{c,rows,get,calls});if(result!==undefined)return result;}
    if(entry.method==='GET' && entry.path.startsWith('/notes?'))return response({groups:options.groups || [],total:(options.groups || []).length});
    if(entry.method==='GET' && entry.path.startsWith('/notes/tracking?'))return response({notes:rows});
    if(entry.method==='GET' && entry.path==='/notes/tracking')return response({notes:rows});
    if(entry.method==='GET' && entry.path.startsWith('/notes/tracking/'))return rows.find(x=>entry.path.endsWith('/'+x.id))?response(rows.find(x=>entry.path.endsWith('/'+x.id))):response({detail:'追踪记录不存在'},404);
    if(entry.method==='POST' && entry.path==='/notes/track-url'){
      const sent=JSON.parse(request.body);
      return response({id:TRACK_A,status:'needs_manual',note_title:'合成已保存笔记',source_note_id:sent.source_note_id,source_root_note_id:NOTE_A,next_check_at:null,message:'已建立手工表现记录，请填写本人实际数据；未经平台核验'});
    }
    if(entry.method==='POST' && entry.path.endsWith('/fill'))return response({ok:true,actual_ces:0,grade:'低',confidence:0.2,confidence_label:'低',training_eligible:false});
    if(entry.method==='DELETE')return response({ok:true});
    assert.fail('Unexpected synthetic request '+entry.method+' '+entry.path);
  };
  const helpers=['_chatOwnerId','_chatIdentitySnapshot','_chatIdentityMatches','authHeader','profileIdentityCurrent','profileReadJSON','profileText','profileRegionError',
    'accountActionStart','accountActionJSON','loadTrackingIndex','trackingStatusMeta','renderLibraryTrackingBadge','trackingForVersionGroup','profileScoreKind','profileRecordDescription'];
  vm.runInContext(helpers.map(source).join('\n')+'\n'+trackingSource(),c);
  const writes=(method='POST',suffix)=>calls.filter(x=>x.method===method&&(!suffix||x.path.endsWith(suffix)));
  return {c,get,doc,calls,toasts,routes,prompts,promptDefaults,confirmations,libraryReads,rows,answers,writes,
    async create(url=URL_A) {await c.trackNoteFromLibrary(NOTE_A,'合成已保存笔记','美食',0);get('track-url-input').value=url;return c.submitTrackUrl();},
    async prepare() {await c.loadTrackingList();},
    switchOwner({sameToken=false,sameOwner=false}={}) {c._chatUserStateEpoch++;if(!sameOwner)c._authUser={id:OWNER_B};if(!sameToken)c._authToken='synthetic-token-b';c._authVerifiedOwnerId=c._authUser.id;},
    visible() {return [...doc.nodes.values()].filter(el=>!el.removed).map(el=>el.textContent).join('\n')+'\n'+toasts.join('\n');},
  };
}

test('manual capability creates from the exact saved version while automatic tracking stays closed',async()=>{
  const f=fixture();await f.create(URL_A+'?xsec_token=synthetic-secret#fragment');await flush();
  const writes=f.writes('POST','/track-url');assert.equal(writes.length,1);
  const body=JSON.parse(writes[0].request.body);
  assert.equal(body.collection_mode,'manual');assert.equal(body.source_note_id,NOTE_A);assert.equal(body.xhs_url,URL_A);
  assert.equal(Object.hasOwn(body,'source_session_id'),false);
  if(Object.hasOwn(body,'source_note_version_id'))assert.equal(body.source_note_version_id,NOTE_A);
  assert.equal(f.c._publicStatus.tracking_open,false);assert.match(f.visible(),/手工|手动/);assert.doesNotMatch(f.toasts.join(' '),/24小时|首次采集/);
});

test('generic entry cannot submit a manual record without an existing saved note',async()=>{
  const f=fixture();await f.c.openTrackUrlModal();f.get('track-url-input').value=URL_A;await f.c.submitTrackUrl();
  assert.equal(f.writes().length,0);assert.ok(f.routes.includes('library')||/笔记库|已保存笔记/.test(f.visible()));
});

test('unavailable manual capability prevents modal creation and direct mutation',async()=>{
  const f=fixture({capabilities:{tracking_manual_open:false}});await f.create();
  assert.equal(f.writes().length,0);assert.equal(f.get('track-url-modal').style.display,'none');
});

for(const bad of ['http://www.xiaohongshu.com/explore/abcdef0123456789abcdef01','https://xhslink.com/a/synthetic','https://evil.invalid/explore/abcdef0123456789abcdef01','https://user:pass@www.xiaohongshu.com/explore/abcdef0123456789abcdef01']) {
  test('invalid or short URL never dispatches: '+bad,async()=>{const f=fixture();await f.create(bad);assert.equal(f.writes().length,0);});
}

for(const status of [400,403,404,409,422]) {
  test('create preserves backend refusal '+status+' without claiming success',async()=>{
    const reason='合成服务端拒绝 '+status,f=fixture({respond:r=>r.method==='POST'?response({detail:reason},status):undefined});
    await f.create();assert.equal(f.writes().length,1);assert.match(f.visible(),new RegExp(reason));assert.doesNotMatch(f.toasts.join(' '),/已建立|已关联|追踪已开始/);
  });
}

for(const receipt of [{},{ok:true},{id:TRACK_A,status:'pending',source_note_id:NOTE_A,next_check_at:'2026-09-20T00:00:00Z'},
  {id:TRACK_A,status:'needs_manual',source_note_id:NOTE_B,next_check_at:null}]) {
  test('unconfirmed or mismatched create receipt is not accepted: '+JSON.stringify(receipt),async()=>{
    const f=fixture({respond:r=>r.method==='POST'?response(receipt):undefined});await f.create();
    assert.doesNotMatch(f.toasts.join(' '),/已建立|已关联|追踪已开始/);assert.equal(f.get('track-url-modal').style.display,'flex');
  });
}

test('create pending and unknown responses cannot dispatch a duplicate automatically',async()=>{
  const late=deferred(),f=fixture({respond:r=>r.method==='POST'?late.promise:undefined});
  const first=f.create();await flush();await f.c.submitTrackUrl();assert.equal(f.writes().length,1);
  late.reject(Error('synthetic disconnected'));await first;await f.c.submitTrackUrl();assert.equal(f.writes().length,1);
  assert.match(f.visible(),/未确认|核实|未知/);
});

for(const identity of [{},{sameOwner:true,sameToken:true}]) {
  test('late creation cannot repaint a changed owner or epoch '+JSON.stringify(identity),async()=>{
    const late=deferred(),f=fixture({respond:r=>r.method==='POST'?late.promise:undefined});
    const run=f.create();await flush();f.switchOwner(identity);f.get('track-url-error').textContent='新会话界面';
    late.resolve(response({id:TRACK_A,status:'needs_manual',source_note_id:NOTE_A,source_root_note_id:NOTE_A,next_check_at:null}));await run;
    assert.equal(f.get('track-url-error').textContent,'新会话界面');assert.equal(f.toasts.length,0);assert.equal(f.libraryReads.length,0);
  });
}

test('four manual prompts preserve actual zero and unknown views as null',async()=>{
  const f=fixture({answers:['0','0','0','']});await f.prepare();await f.c.openManualFill(TRACK_A);await flush();
  assert.equal(f.writes('POST','/fill').length,1);
  assert.deepEqual(JSON.parse(f.writes('POST','/fill')[0].request.body),{likes:0,saves:0,comments:0,views:null,evidence_source:'manual'});
  assert.equal(f.prompts.length,4);
});

for(let cancelAt=0;cancelAt<4;cancelAt++) {
  test('cancel prompt '+(cancelAt+1)+' never submits zero in its place',async()=>{
    const f=fixture({answers:[...Array(cancelAt).fill('0'),null]});await f.prepare();await f.c.openManualFill(TRACK_A);await flush();assert.equal(f.writes().length,0);
  });
}

for(const invalid of ['', '-1','1.5','2cats','2147483648','NaN','Infinity']) {
  test('invalid interaction counter is rejected rather than coerced: '+JSON.stringify(invalid),async()=>{
    const f=fixture({answers:[invalid,'0','0','']});await f.prepare();await f.c.openManualFill(TRACK_A);await flush();assert.equal(f.writes().length,0);
  });
}

test('known zero views and maximum supported integer remain unchanged',async()=>{
  const f=fixture({answers:['2147483647','0','0','0']});await f.prepare();await f.c.openManualFill(TRACK_A);await flush();
  const body=JSON.parse(f.writes('POST','/fill')[0].request.body);assert.equal(body.likes,2147483647);assert.equal(body.views,0);
});

test('active provider attempt prevents fill and delete regardless of status or direct invocation',async()=>{
  const f=fixture({rows:[row({provider_attempt_state:'in_progress'})],answers:['1','2','3','']});await f.prepare();
  await f.c.openManualFill(TRACK_A);await f.c.submitManualFill(TRACK_A,1,2,3,null);await f.c.deleteTrackingRecord(TRACK_A);await flush();
  assert.equal(f.writes().length,0);assert.equal(f.writes('DELETE').length,0);
});

test('read-only capability allows rows and detail but never fill or delete',async()=>{
  const f=fixture({capabilities:{tracking_manual_open:false,tracking_delete_open:false}});await f.prepare();await f.c.openTrackingDetail(TRACK_A);
  await f.c.openManualFill(TRACK_A);await f.c.submitManualFill(TRACK_A,0,0,0,null);await f.c.deleteTrackingRecord(TRACK_A);
  assert.ok(f.calls.some(r=>r.method==='GET'&&r.path.endsWith(TRACK_A)));assert.equal(f.writes().length,0);assert.equal(f.writes('DELETE').length,0);
});

test('completed records cannot be refilled',async()=>{
  const f=fixture({rows:[row({status:'complete'})],answers:['1','2','3','']});await f.prepare();await f.c.openManualFill(TRACK_A);await f.c.submitManualFill(TRACK_A,1,2,3,null);await flush();assert.equal(f.writes().length,0);
});

test('fill requires both successful HTTP and explicit ok:true',async()=>{
  for(const reply of [response({ok:true,actual_ces:77},500),response({ok:false,detail:'合成填报拒绝'}),response({actual_ces:77})]) {
    const f=fixture({respond:r=>r.path.endsWith('/fill')?reply:undefined});await f.prepare();await f.c.submitManualFill(TRACK_A,0,0,0,null);await flush();
    assert.equal(f.writes().length,1);assert.doesNotMatch(f.toasts.join(' '),/✅|已保存|已完成|实际 CES:/);
  }
});

test('fill pending and unknown responses do not trigger a second mutation',async()=>{
  const late=deferred(),f=fixture({respond:r=>r.path.endsWith('/fill')?late.promise:undefined});await f.prepare();
  const first=f.c.submitManualFill(TRACK_A,0,0,0,null);await flush();await f.c.submitManualFill(TRACK_A,0,0,0,null);
  assert.equal(f.writes('POST','/fill').length,1);late.reject(Error('synthetic disconnected'));await first;
  await f.c.submitManualFill(TRACK_A,0,0,0,null);assert.equal(f.writes('POST','/fill').length,1);assert.match(f.visible(),/未确认|核实|未知/);
});

test('late successful fill cannot announce success or refresh another account',async()=>{
  const late=deferred(),f=fixture({respond:r=>r.path.endsWith('/fill')?late.promise:undefined});await f.prepare();
  const run=f.c.submitManualFill(TRACK_A,0,0,0,null);await flush();f.switchOwner();f.get('profile-tracking-list').textContent='新账户追踪记录';
  late.resolve(response({ok:true,actual_ces:0,confidence_label:'低'}));await run;
  assert.equal(f.get('profile-tracking-list').textContent,'新账户追踪记录');assert.equal(f.toasts.length,0);assert.equal(f.libraryReads.length,0);
});

test('delete preserves confirmation and backend active-attempt refusal',async()=>{
  const cancelled=fixture({confirm:false});await cancelled.prepare();await cancelled.c.deleteTrackingRecord(TRACK_A);assert.equal(cancelled.writes('DELETE').length,0);
  const blocked=fixture({respond:r=>r.method==='DELETE'?response({detail:'采集尝试正在结算，请稍后再删除'},409):undefined});
  await blocked.prepare();await blocked.c.deleteTrackingRecord(TRACK_A);assert.equal(blocked.writes('DELETE').length,1);assert.match(blocked.visible(),/采集尝试正在结算/);assert.doesNotMatch(blocked.toasts.join(' '),/已删除/);
});

test('delete only announces success after 2xx and ok:true',async()=>{
  for(const reply of [response({ok:true},500),response({ok:false}),response({})]) {
    const f=fixture({respond:r=>r.method==='DELETE'?reply:undefined});await f.prepare();await f.c.deleteTrackingRecord(TRACK_A);
    assert.equal(f.writes('DELETE').length,1);assert.doesNotMatch(f.toasts.join(' '),/已删除/);
  }
  const valid=fixture();await valid.prepare();await valid.c.deleteTrackingRecord(TRACK_A);
  assert.equal(valid.writes('DELETE').length,1);assert.match(valid.toasts.join(' '),/已删除/);
});

test('uncertain deletion cannot be automatically or blindly resubmitted',async()=>{
  const f=fixture({respond:r=>r.method==='DELETE'?Promise.reject(Error('synthetic disconnected')):undefined});await f.prepare();
  await f.c.deleteTrackingRecord(TRACK_A);await f.c.deleteTrackingRecord(TRACK_A);
  assert.equal(f.writes('DELETE').length,1);assert.match(f.visible(),/未确认|核实|未知/);
});

test('list HTTP and JSON failures stay visible instead of becoming an empty list',async()=>{
  for(const reply of [response({notes:[]},503),{ok:false,status:404,json:async()=>{throw Error('HTML');}},response({})]) {
    const f=fixture({respond:r=>r.path==='/notes/tracking'?reply:undefined});await f.c.loadTrackingList();
    assert.match(f.get('profile-tracking-list').textContent,/失败|无法|不完整/);assert.doesNotMatch(f.get('profile-tracking-list').textContent,/暂无追踪|暂无已有/);
  }
});

test('version badges never borrow a later version record through its root ID',async()=>{
  const f=fixture({rows:[row({id:TRACK_B,source_note_id:NOTE_B,source_root_note_id:NOTE_A,status:'complete',actual_ces:81})]});
  await f.c.loadTrackingIndex();
  assert.equal(f.c._trackingBySourceNote.get(NOTE_B)?.id,TRACK_B);assert.equal(f.c._trackingBySourceNote.has(NOTE_A),false);
  assert.doesNotMatch(f.c.renderLibraryTrackingBadge(NOTE_A),/81\.0|已完成/);assert.match(f.c.renderLibraryTrackingBadge(NOTE_B),/81\.0/);
});

test('late tracking index cannot replace the next account map',async()=>{
  const late=deferred(),f=fixture({respond:r=>r.path==='/notes/tracking'?late.promise:undefined});const run=f.c.loadTrackingIndex();await flush();
  f.switchOwner();f.c._trackingBySourceNote=new Map([[NOTE_B,{id:TRACK_B}]]);late.resolve(response({notes:[row()]}));await run;
  assert.equal(f.c._trackingBySourceNote.get(NOTE_B)?.id,TRACK_B);assert.equal(f.c._trackingBySourceNote.has(NOTE_A),false);
});

test('detail identity mismatch never displays another tracking row as the selected record',async()=>{
  const f=fixture({respond:r=>r.path==='/notes/tracking/'+TRACK_A?response(row({id:TRACK_B,note_title:'不得显示的另一条记录'})):undefined});
  await f.prepare();await f.c.openTrackingDetail(TRACK_A);assert.doesNotMatch(f.visible(),/不得显示的另一条记录/);assert.match(f.visible(),/不一致|不匹配|未确认|无法/);
});

test('uncertain creation is recovered only by a read of the exact canonical URL and saved version',async()=>{
  const f=fixture({respond:r=>r.method==='POST'?Promise.reject(Error('synthetic disconnected')):undefined});
  await f.create();await f.c.verifyTrackingSubmission();
  assert.equal(f.writes().length,1);assert.ok(f.calls.some(r=>r.method==='GET'&&r.path==='/notes/tracking'));
  assert.equal(f.get('track-url-modal').style.display,'none');assert.match(f.toasts.join(' '),/没有重复创建/);
});

test('an unrelated version or URL cannot falsely confirm an uncertain creation',async()=>{
  for(const extra of [{source_note_id:NOTE_B},{xhs_url:URL_B}]) {
    const f=fixture({rows:[row(extra)],respond:r=>r.method==='POST'?Promise.reject(Error('synthetic disconnected')):undefined});
    await f.create();await f.c.verifyTrackingSubmission();
    assert.equal(f.writes().length,1);assert.equal(f.get('track-url-modal').style.display,'flex');
    assert.doesNotMatch(f.toasts.join(' '),/已核对到/);assert.match(f.visible(),/未找到/);
  }
});

test('ambiguous or failed readback keeps unknown creation blocked',async()=>{
  for(const reply of [response({notes:[row(),row({id:TRACK_B})]}),response({notes:[]},503),response({})]) {
    const f=fixture({respond:r=>r.method==='POST'?Promise.reject(Error('synthetic disconnected')):r.path==='/notes/tracking'?reply:undefined});
    await f.create();await f.c.verifyTrackingSubmission();await f.c.submitTrackUrl();
    assert.equal(f.writes().length,1);assert.equal(f.get('track-url-modal').style.display,'flex');assert.doesNotMatch(f.toasts.join(' '),/已核对到/);
  }
});

test('confirmed absence permits a later explicit submit, never an automatic second creation',async()=>{
  const f=fixture({rows:[],respond:r=>r.method==='POST'?Promise.reject(Error('synthetic disconnected')):undefined});
  await f.create();await f.c.verifyTrackingSubmission();assert.equal(f.writes().length,1);assert.equal(f.get('track-url-btn').disabled,false);
  await f.c.submitTrackUrl();assert.equal(f.writes().length,2);
});

test('current detail readback clears an uncertain fill without issuing a new mutation',async()=>{
  const f=fixture({respond:(r,{rows})=>{if(r.path.endsWith('/fill')){rows[0]={...rows[0],status:'complete',actual_ces:0};throw Error('synthetic disconnected');}}});
  await f.prepare();await f.c.submitManualFill(TRACK_A,0,0,0,null);await f.c.openTrackingDetail(TRACK_A);await f.c.submitManualFill(TRACK_A,0,0,0,null);
  assert.equal(f.writes().length,1);assert.match(f.get('tracking-detail-'+TRACK_A).textContent,/已完成/);assert.match(f.get('tracking-detail-'+TRACK_A).textContent,/未经平台核验/);
});

test('clearing account tracking state removes selectable notes and closes the old modal',async()=>{
  const f=fixture();await f.prepare();await f.c.loadTrackingIndex();await f.c.trackNoteFromLibrary(NOTE_A,'合成笔记','美食',0);
  assert.equal(f.get('track-url-modal').style.display,'flex');f.c.clearTrackingUserState();
  assert.equal(f.get('track-url-modal').style.display,'none');assert.equal(f.c._librarySelectableNotes.size,0);assert.equal(f.c._trackingBySourceNote.size,0);
  await f.c.trackNoteFromLibrary(NOTE_A,'旧账号笔记','美食',0);f.get('track-url-input').value=URL_A;await f.c.submitTrackUrl();assert.equal(f.writes().length,0);
});

test('the actual library read caches server versions for the current owner, not caller-supplied metadata',async()=>{
  const saved={id:NOTE_A,title:'服务端笔记',body:'合成正文',domain:'旅行',version:3,score:0};
  const f=fixture({groups:[{group_id:NOTE_A,latest:saved,versions:[saved]}]});f.c._librarySelectableNotes=new Map();f.c._libraryIdentity=null;
  f.c.buildGroupCard=()=>new Element('div',f.doc);vm.runInContext(source('loadLibrary'),f.c);
  await f.c.loadLibrary(true);await f.c.trackNoteFromLibrary(NOTE_A,'伪造参数','美食',99);
  assert.equal(f.get('track-url-source').textContent,'关联笔记：服务端笔记 · v3');assert.equal(f.get('track-url-ces').value,'0');assert.equal(f.get('track-url-domain').value,'旅行');
});

test('late library data cannot populate selectable notes for the next owner',async()=>{
  const late=deferred(),f=fixture({respond:r=>r.path.startsWith('/notes?')?late.promise:undefined});
  f.c.buildGroupCard=()=>new Element('div',f.doc);vm.runInContext(source('loadLibrary'),f.c);
  const run=f.c.loadLibrary(true);await flush();f.switchOwner();f.c._librarySelectableNotes=new Map([[NOTE_B,{id:NOTE_B}]]);
  late.resolve(response({groups:[{group_id:NOTE_A,latest:{id:NOTE_A},versions:[{id:NOTE_A}]}],total:1}));await run;
  assert.equal(f.c._librarySelectableNotes.has(NOTE_A),false);assert.equal(f.c._librarySelectableNotes.has(NOTE_B),true);
});

test('a detail response started before confirmed deletion cannot resurrect the deleted row',async()=>{
  const late=deferred(),f=fixture({respond:(r,{rows})=>{
    if(r.method==='GET'&&r.path==='/notes/tracking/'+TRACK_A)return late.promise;
    if(r.method==='DELETE'){rows.length=0;return response({ok:true});}
  }});
  await f.prepare();const detail=f.c.openTrackingDetail(TRACK_A);await flush();await f.c.deleteTrackingRecord(TRACK_A);
  assert.match(f.get('profile-tracking-list').textContent,/暂无/);
  late.resolve(response(row()));await detail;
  assert.match(f.get('profile-tracking-list').textContent,/暂无/);assert.doesNotMatch(f.get('profile-tracking-list').textContent,/合成已保存笔记/);
});

test('a detail response started before confirmed fill cannot restore the old editable status',async()=>{
  const late=deferred(),f=fixture({respond:(r,{rows})=>{
    if(r.method==='GET'&&r.path==='/notes/tracking/'+TRACK_A)return late.promise;
    if(r.method==='POST'&&r.path.endsWith('/fill')){rows[0]={...rows[0],status:'complete',actual_ces:0};return response({ok:true,actual_ces:0,confidence_label:'低'});}
  }});
  await f.prepare();const detail=f.c.openTrackingDetail(TRACK_A);await flush();await f.c.submitManualFill(TRACK_A,0,0,0,null);
  assert.match(f.get('profile-tracking-list').textContent,/已完成/);late.resolve(response(row()));await detail;
  assert.match(f.get('profile-tracking-list').textContent,/已完成/);assert.doesNotMatch(f.get('profile-tracking-list').textContent,/待录入互动数据/);
});

test('a list response started before a newer detail cannot overwrite that exact current record',async()=>{
  const late=deferred();let lists=0;
  const f=fixture({respond:r=>{
    if(r.method==='GET'&&r.path==='/notes/tracking'&&++lists===2)return late.promise;
    if(r.method==='GET'&&r.path==='/notes/tracking/'+TRACK_A)return response(row({status:'complete',actual_ces:0}));
  }});
  await f.prepare();const oldList=f.c.loadTrackingList();await flush();await f.c.openTrackingDetail(TRACK_A);
  assert.match(f.get('profile-tracking-list').textContent,/已完成/);late.resolve(response({notes:[row()]}));await oldList;
  assert.match(f.get('profile-tracking-list').textContent,/已完成/);assert.doesNotMatch(f.get('profile-tracking-list').textContent,/待录入互动数据/);
});

test('manual growth records explicitly describe a computed score from unverified user input',()=>{
  const f=fixture();const record={action:'url_track',score_kind:'performance',score:0,source_type:'tracking',source_id:TRACK_A,note_id:NOTE_A};
  assert.equal(f.c.profileScoreKind(record),'performance');
  const text=f.c.profileRecordDescription(record);
  assert.match(text,/用户录入表现的计算评分，未经平台核验/);assert.match(text,new RegExp(TRACK_A));assert.doesNotMatch(text,/平台已核验|自动采集/);
});

test('existing crawler growth actions are not relabeled as manually entered records',()=>{
  const f=fixture();for(const action of ['url_crawl_3d','url_crawl_7d']) {
    const text=f.c.profileRecordDescription({action,score_kind:'performance',source_type:'tracking',source_id:TRACK_A});
    assert.match(text,/发布后表现（来源见记录）/);assert.doesNotMatch(text,/用户录入表现/);
  }
});

test('missing growth provenance stays a legacy score instead of gaining manual or crawler attribution',()=>{
  const f=fixture(),record={score:0,id:'synthetic-legacy'};
  assert.equal(f.c.profileScoreKind(record),'legacy');assert.match(f.c.profileRecordDescription(record),/历史评分（类型未记录）/);
  assert.doesNotMatch(f.c.profileRecordDescription(record),/用户录入表现|自动采集|平台已核验/);
});

test('parallel deletions cannot invalidate the last successful list and leave it loading',async()=>{
  const delA=deferred(),delB=deferred(),listA=deferred(),listB=deferred();let lists=0;
  const f=fixture({rows:[row(),row({id:TRACK_B,source_note_id:NOTE_B})],respond:r=>{
    if(r.method==='DELETE')return r.path.endsWith(TRACK_A)?delA.promise:delB.promise;
    if(r.path==='/notes/tracking'&&r.method==='GET'){lists++;if(lists===2)return listA.promise;if(lists===3)return listB.promise;}
  }});
  await f.prepare();const first=f.c.deleteTrackingRecord(TRACK_A),second=f.c.deleteTrackingRecord(TRACK_B);
  delA.resolve(response({ok:true}));await flush();delB.resolve(response({ok:true}));await flush();
  listA.resolve(response({notes:[]}));await first;listB.resolve(response({notes:[]}));await second;
  assert.equal(f.writes('DELETE').length,2);assert.match(f.get('profile-tracking-list').textContent,/暂无/);
  assert.doesNotMatch(f.get('profile-tracking-list').textContent,/正在读取/);
});

test('failed manual input retains prompt defaults until account state is cleared',async()=>{
  const f=fixture({answers:['12','2','0',''],respond:r=>r.path.endsWith('/fill')?response({},503):undefined});
  await f.prepare();await f.c.openManualFill(TRACK_A);assert.equal(f.writes().length,1);
  await f.c.openTrackingDetail(TRACK_A);f.answers.push('12','2','0',null);await f.c.openManualFill(TRACK_A);
  assert.deepEqual(f.promptDefaults.slice(4,8),['12','2','0','']);assert.equal(f.writes().length,1);
  f.c.clearTrackingUserState();await f.prepare();f.answers.push(null);await f.c.openManualFill(TRACK_A);
  assert.equal(f.promptDefaults.at(-1),'');assert.equal(f.writes().length,1);
});

test('views provenance preserves explicit zero and distinguishes manual input from system estimates',()=>{
  const f=fixture();for(const asJSON of [false,true])for(const estimated of [false,true]) {
    const facts={schema_version:'performance_score_v1',metrics:{views_est:0,views_estimated:estimated}};
    const result=f.c.trackingViewsDescription(row({views_est:0,insights_json:asJSON?JSON.stringify(facts):facts}));
    assert.equal(result[1],'0');assert.match(result[0],estimated?/系统估算，非平台实测/:/用户录入，未经平台核验/);
  }
});

test('non-manual views with verified metadata retain their recorded source without inventing platform verification',()=>{
  const f=fixture();const result=f.c.trackingViewsDescription(row({evidence_source:'crawler',views_est:50,
    insights_json:{schema_version:'performance_score_v1',metrics:{views_est:50,views_estimated:false}}}));
  assert.equal(result[1],'50');assert.match(result[0],/按记录来源展示/);assert.doesNotMatch(result[0],/用户录入|系统估算|平台已核验/);
});

test('missing, malformed, mismatched or non-boolean views metadata cannot invent provenance',()=>{
  const f=fixture();const valid={schema_version:'performance_score_v1',metrics:{views_est:50,views_estimated:false}};
  for(const facts of [undefined,null,'bad JSON',{},[],{...valid,schema_version:'future_v2'},
    {...valid,metrics:{views_est:51,views_estimated:false}},{...valid,metrics:{views_est:'50',views_estimated:false}},
    {...valid,metrics:{views_est:50,views_estimated:'false'}},{...valid,metrics:{views_est:50}}]) {
    const result=f.c.trackingViewsDescription(row({views_est:50,insights_json:facts}));
    assert.equal(result[1],'50');assert.match(result[0],/来源未记录/);
  }
});

test('unknown or nonnumeric views never become measured zero',()=>{
  const f=fixture();for(const views of [undefined,null,'0',NaN,Infinity]) {
    const result=f.c.trackingViewsDescription(row({views_est:views,insights_json:{schema_version:'performance_score_v1',metrics:{views_est:views,views_estimated:false}}}));
    assert.equal(result[1],'未记录');assert.match(result[0],/来源未记录/);
  }
});
