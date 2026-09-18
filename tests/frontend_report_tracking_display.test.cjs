const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','NoteAI_Pro_Demo_Framer.html'),'utf8');
const sources=new Map();
function source(name){
  if(sources.has(name))return sources.get(name);
  const start=html.search(new RegExp('^(?:async )?function '+name+'\\(','m'));
  assert.ok(start>=0,'Actual HTML function exists: '+name);
  for(let end=html.indexOf('\n',start);end>=0;end=html.indexOf('\n',end+1)){
    const candidate=html.slice(start,end);
    try{new vm.Script(candidate);sources.set(name,candidate);return candidate;}catch{/* Incomplete declaration. */}
  }
  assert.fail('Unable to extract '+name);
}
const OWNER='11111111-1111-4111-8111-111111111111';
const OTHER_OWNER='22222222-2222-4222-8222-222222222222';
const NOTE='33333333-3333-4333-8333-333333333333';
const VERSION='44444444-4444-4444-8444-444444444444';
const TRACK='55555555-5555-4555-8555-555555555555';
const OTHER_TRACK='66666666-6666-4666-8666-666666666666';
function record(extra={}){return {id:TRACK,user_id:OWNER,source_note_id:NOTE,source_root_note_id:NOTE,status:'complete',evidence_source:'manual',actual_ces:0,training_eligible:false,...extra};}
function fixture(capabilities={tracking_read_open:true,tracking_manual_open:true,tracking_open:false}){
  const nodes=new Map(),network=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{style:{},innerHTML:'',textContent:''});return nodes.get(id);};
  const c=vm.createContext({console,Map,Set,PUBLIC_PRODUCT:true,_authToken:'synthetic-token-a',_authUser:{id:OWNER},_chatUserStateEpoch:3,
    _publicStatus:capabilities,_trackingReadRevision:7,_reportTrackingSnapshot:null,_reportTrackingSnapshotSequence:0,
    _profileViewState:null,_libraryIdentity:null,_trackingBySourceNote:new Map(),_trackingRecords:new Map(),
    document:{getElementById:get},fetch:(...args)=>{network.push(args);throw Error('Report display must not dispatch a network request');}});
  const functions=['escapeHtml','_chatOwnerId','_chatIdentitySnapshot','_chatIdentityMatches','profileIdentityCurrent',
    'completeProductResult','_numOrNull','formatScoreValue','diagnosisDisplayScore','scoreColor','trackingManualAvailable',
    'trackingStatusMeta','trackingManualNotice','trackingNumber','rememberReportTrackingSnapshot','reportTrackingPresentation','renderReportLifecycle'];
  vm.runInContext(functions.map(source).join('\n'),c);
  return {c,get,network,
    remember(notes){c.rememberReportTrackingSnapshot(notes,c._chatIdentitySnapshot(),c._authToken);},
    presentation(id=NOTE){return c.reportTrackingPresentation(id);},
    render(extra={}){c.renderReportLifecycle({_saved_note_id:NOTE,composite_score:70,_inputTitle:'合成诊断',...extra});return get('report-loop-steps').innerHTML.replace(/<[^>]*>/g,'');},
  };
}
const describe=step=>[step.title,step.value,step.note].join(' · ');

test('manual-open unassociated report guides the original library flow without promising automatic collection',()=>{
  const f=fixture();f.remember([]);
  const text=f.render();assert.match(text,/当前版本尚无关联记录/);assert.match(text,/笔记库/);
  assert.doesNotMatch(text,/24h|24小时|7d|7天后.*采集|会校准预测|已训练/);assert.equal(f.network.length,0);
});

test('never-read tracking is distinct from a successful empty snapshot',()=>{
  const f=fixture();assert.match(describe(f.presentation().tracking),/关联状态待读取/);
  f.remember([]);assert.match(describe(f.presentation().tracking),/当前版本尚无关联记录/);
});

test('a report without a saved note ID does not borrow unrelated cached tracking',()=>{
  const f=fixture();f.remember([record({actual_ces:87})]);
  const text=describe(f.presentation(null).tracking);assert.match(text,/需关联已保存笔记/);assert.doesNotMatch(text,/87/);
});

test('closed manual capability does not promise that manual entry or automatic collection is open',()=>{
  const f=fixture({tracking_read_open:true,tracking_manual_open:false,tracking_open:false});f.remember([]);
  const text=describe(f.presentation().tracking);assert.match(text,/未开放|暂不可用|当前不可用|暂未开放/);
  assert.doesNotMatch(text,/(?:手工|手动|自动采集)[^；。]*已开放|已开放(?:手工|手动|自动采集)|立即录入|可建立|24h|7d/);assert.equal(f.network.length,0);
});

test('missing capability is unknown rather than a false claim of enabled service',()=>{
  const f=fixture({tracking_read_open:true});f.remember([]);
  const text=describe(f.presentation().tracking);assert.match(text,/未确认|待确认|待核|暂无法确认/);
  assert.doesNotMatch(text,/(?:手工|手动|自动采集)[^；。]*已开放|已开放(?:手工|手动|自动采集)|立即录入|可建立/);
});

test('exact own manual record preserves a zero score and unverified provenance in the actual report cards',()=>{
  const f=fixture();f.remember([record()]);const p=f.presentation(),text=f.render();
  assert.match(describe(p.tracking),/0(?:\.0)?\s*分|评分\s*0/);assert.match(describe(p.tracking),/用户录入|手工|手动/);
  assert.match(text,/未经平台核验/);assert.doesNotMatch(describe(p.learning),/已训练|已学习|已校准|已沉淀/);assert.equal(f.network.length,0);
});

test('manual_filled explicitly retains manual provenance even when the older source field is absent',()=>{
  const f=fixture();f.remember([record({evidence_source:null,manual_filled:1})]);
  assert.match(describe(f.presentation().tracking),/用户录入|手工|手动/);assert.match(describe(f.presentation().tracking),/未经平台核验/);
});

test('read-only historical record with unknown source does not gain a verification or training claim',()=>{
  const f=fixture({tracking_read_open:true,tracking_manual_open:false,tracking_open:false});
  f.remember([record({actual_ces:42,evidence_source:null,training_eligible:true})]);const p=f.presentation();
  assert.match(describe(p.tracking),/42/);assert.match(describe(p.tracking),/来源未记录|来源待核|来源未确认/);
  assert.doesNotMatch(describe(p.tracking),/用户录入|自动采集|平台已核验|平台核验通过/);
  assert.doesNotMatch(describe(p.learning),/已训练|已学习|已校准|已沉淀/);
});

test('same root but another saved version cannot supply this report performance',()=>{
  const f=fixture();f.remember([record({source_note_id:VERSION,source_root_note_id:NOTE,actual_ces:87})]);
  const text=describe(f.presentation().tracking);assert.match(text,/当前版本尚无关联记录/);assert.doesNotMatch(text,/87/);
});

test('an explicit foreign row is not accepted even inside a current-owner snapshot',()=>{
  const f=fixture();f.remember([record({user_id:OTHER_OWNER,actual_ces:87})]);
  assert.doesNotMatch(describe(f.presentation().tracking),/87/);
});

for(const boundary of ['owner','token','epoch','revision']){
  test('tracking snapshot cannot outlive its '+boundary+' boundary',()=>{
    const f=fixture();f.remember([record({actual_ces:87})]);
    if(boundary==='owner')f.c._authUser={id:OTHER_OWNER};
    if(boundary==='token')f.c._authToken='synthetic-token-b';
    if(boundary==='epoch')f.c._chatUserStateEpoch++;
    if(boundary==='revision')f.c._trackingReadRevision++;
    const text=describe(f.presentation().tracking);assert.match(text,/关联状态待读取/);assert.doesNotMatch(text,/87/);
  });
}

test('multiple exact records show their count instead of choosing an arbitrary performance score',()=>{
  const f=fixture();f.remember([record({actual_ces:31}),record({id:OTHER_TRACK,actual_ces:88})]);
  const text=describe(f.presentation().tracking);assert.match(text,/2\s*(条|份|个)/);assert.doesNotMatch(text,/31|88/);
});

test('unbound profile or library caches cannot masquerade as a report tracking snapshot',()=>{
  const f=fixture();f.c._trackingBySourceNote.set(NOTE,record({actual_ces:87}));f.c._trackingRecords.set(TRACK,record({actual_ces:87}));
  f.c._profileViewState={identity:f.c._chatIdentitySnapshot(),token:f.c._authToken,values:{tracking:{notes:[record({actual_ces:87})]}}};
  f.c._libraryIdentity={identity:f.c._chatIdentitySnapshot(),token:f.c._authToken};
  const text=describe(f.presentation().tracking);assert.match(text,/关联状态待读取/);assert.doesNotMatch(text,/87/);
});

test('failed or absent report still hides the existing lifecycle card',()=>{
  const f=fixture();for(const result of [null,{_error:true},{_outcome_unknown:true},{_waiting_for_input:true}]){
    f.c.renderReportLifecycle(result);assert.equal(f.get('reportLifecycleCard').style.display,'none');
  }
  assert.equal(f.network.length,0);
});

test('radar heading describes dimensions without hard-coding a five-dimension result',()=>{
  const chart=html.indexOf('id="radarChart"');assert.ok(chart>=0);
  const headings=[...html.slice(Math.max(0,chart-500),chart).matchAll(/<h2\b[^>]*>([\s\S]*?)<\/h2>/g)];
  assert.ok(headings.length);const label=headings.at(-1)[1].replace(/<[^>]*>/g,'');
  assert.match(label,/雷达/);assert.doesNotMatch(label,/五维|5\s*维/);
});

test('snapshot ingestion rejects an explicitly stale tracking revision',()=>{
  const f=fixture();f.remember([record({actual_ces:65})]);
  f.c.rememberReportTrackingSnapshot([record({actual_ces:31})],f.c._chatIdentitySnapshot(),f.c._authToken,f.c._trackingReadRevision-1);
  assert.match(describe(f.presentation().tracking),/65/);assert.doesNotMatch(describe(f.presentation().tracking),/31/);
});

for(const lateStatus of [200,503]){
  test('older library tracking index '+lateStatus+' cannot replace a newer successful profile snapshot',async()=>{
    const f=fixture();let resolveOld;const oldResponse=new Promise(resolve=>{resolveOld=resolve;});let requests=0;
    Object.assign(f.c,{API_AUTH:'https://synthetic.invalid',_profileTrackingReadSequence:0,_trackingIndexReadSequence:0,
      showToast(){},renderTrackingRows(){},renderProfileLoopInsights(){}});
    const response=(notes,status=200)=>({ok:status>=200&&status<300,status,json:async()=>({notes})});
    f.c.fetch=async(url,options)=>{
      assert.equal(url,'https://synthetic.invalid/notes/tracking');assert.equal(options.headers.Authorization,'Bearer synthetic-token-a');
      requests++;return requests===1?oldResponse:response([record({actual_ces:65})]);
    };
    const functions=['profileReadJSON','profileText','profileRegionError','profileTrackingAvailable','trackingRequestContext','updateProfileTrackingInsights','loadTrackingIndex','loadTrackingList'];
    vm.runInContext(functions.map(source).join('\n'),f.c);
    const index=f.c.loadTrackingIndex();await Promise.resolve();await f.c.loadTrackingList();
    assert.match(describe(f.presentation().tracking),/65/);resolveOld(response([record({actual_ces:31})],lateStatus));await index;
    assert.equal(requests,2);assert.match(describe(f.presentation().tracking),/65/);assert.doesNotMatch(describe(f.presentation().tracking),/31|待读取/);
  });
}

test('older profile list cannot replace a newer successful library tracking snapshot',async()=>{
  const f=fixture();let resolveOld;const oldResponse=new Promise(resolve=>{resolveOld=resolve;});let requests=0;
  Object.assign(f.c,{API_AUTH:'https://synthetic.invalid',_profileTrackingReadSequence:0,_trackingIndexReadSequence:0,
    showToast(){},renderTrackingRows(){},renderProfileLoopInsights(){}});
  const response=score=>({ok:true,status:200,json:async()=>({notes:[record({actual_ces:score})]})});
  f.c.fetch=async(url,options)=>{
    assert.equal(url,'https://synthetic.invalid/notes/tracking');assert.equal(options.headers.Authorization,'Bearer synthetic-token-a');
    requests++;return requests===1?oldResponse:response(65);
  };
  vm.runInContext(['profileReadJSON','profileText','profileRegionError','profileTrackingAvailable','trackingRequestContext','updateProfileTrackingInsights','loadTrackingIndex','loadTrackingList'].map(source).join('\n'),f.c);
  const list=f.c.loadTrackingList();await Promise.resolve();await f.c.loadTrackingIndex();
  assert.match(describe(f.presentation().tracking),/65/);resolveOld(response(31));await list;
  assert.equal(requests,2);assert.match(describe(f.presentation().tracking),/65/);assert.doesNotMatch(describe(f.presentation().tracking),/31/);
});
