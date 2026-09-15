// Pure VM checks of production functions; no browser, credentials or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const html = fs.readFileSync(require('node:path').join(__dirname, '../NoteAI_Pro_Demo_Framer.html'), 'utf8');
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script); // Detect duplicate declarations and malformed production JS.
function source(name) {
  const match = new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(script);
  assert.ok(match, name);
  for (let end = script.indexOf('}', match.index); end >= 0; end = script.indexOf('}', end+1)) {
    const value = script.slice(match.index, end+1);
    try { new vm.Script(value); return value; } catch {}
  }
  throw Error('Incomplete function '+name);
}
function context(extra={}) {
  const c = vm.createContext({console, Promise, ...extra});
  c.load = (...names) => names.forEach(n=>vm.runInContext(source(n), c));
  return c;
}
test('normal combined note submits all original fields once during image persistence', async()=>{
  let release, requests=[];
  const stored = new Promise(r=>release=r);
  const values={inputTitle:'测试标题',inputDesc:'测试正文 #测试',inputDomain:'旅行',noteMediaType:'video'};
  const c=context({
    PUBLIC_PRODUCT:true, API_BASE:'', _authToken:'synthetic', _authUser:{id:'owner'},
    _diagnosisPreparing:false,_diagnosisStreamActive:false,_diagVideoState:'ready',
    _diagVideoFileId:'video-original',_diagVideoAttempt:1,_coverBase64:'data:image/png;base64,cover',_diagImages:[],
    document:{getElementById:id=>({value:values[id]}),querySelector:()=>({textContent:'填写笔记／上传素材'})},
    requirePublicCapability:()=>true,requireProductConsent:()=>true,
    _chatIdentitySnapshot:()=>({ownerId:'owner'}),_chatIdentityMatches:()=>true,
    getConstraintTags:()=>['不改标题','不改封面'],getContentIntentPayload:()=>({content_intent:'种草'}),
    authHeader:()=>({Authorization:'Bearer synthetic'}),shouldAskMerchantBeforeRun:()=>false,
    privateImageInput:async()=>{await stored;return 'cover-original';},
    updateDiagnosisSubmitState(){},showToast(){},formatLocalTimeWithConstraints:()=> '2026091510',
    createSseWarningGuard:()=>({connected(){},finish(){}}),createPaidRequestId:()=> 'single-test',
    fetch:async(_url,options)=>{requests.push(JSON.parse(options.body));return {status:401};},
    openAuthModal(){},setTimeout(){},
  });
  c.load('diagnosisUsesVideo','startDiagnosis','prepareDiagnosis');
  const first=c.startDiagnosis(); await Promise.resolve(); await c.startDiagnosis();
  assert.equal(requests.length,0);release();await first;await c._diagnosePromise;
  assert.equal(requests.length,1);
  assert.equal(requests[0].video_file_id,'video-original');
  assert.equal(requests[0].cover_image,'cover-original');
  assert.equal(requests[0].note_title,'测试标题');assert.equal(requests[0].desc,'测试正文 #测试');
  assert.equal(requests[0].domain,'旅行');assert.equal(requests[0].input_mode,'video');
  assert.deepEqual(requests[0].user_constraints,['不改标题','不改封面']);
});
for (const kind of ['Diag','Gen']) {
  test(kind+' video does not upload or publish a late result across account changes',async()=>{
    for (const phase of ['metadata','response']) {
      let video, release, calls=0;
      const response = new Promise(r=>release=r);
      const c=context({PUBLIC_PRODUCT:true,_authToken:'first',_diagVideoAttempt:0,_genVideoAttempt:0,
        _chatIdentitySnapshot:()=>({token:'first'}),requirePublicCapability:()=>true,
        URL:{createObjectURL:()=> 'local',revokeObjectURL(){}},FormData:class {append(){}},
        document:{getElementById:()=>({style:{}}),createElement:()=>{video={duration:57};return video;}},
        _setDiagVideoState(s){c.diagState=s;},_setGenVideoState(s){c.genState=s;},
        fetch:async()=>{calls++;return response;},API_BASE:'',showToast(){},openAuthModal(){},
      });
      c._chatIdentityMatches=id=>id.token===c._authToken;
      const name=kind==='Diag'?'_uploadDiagVideoFile':'_uploadVideoFile';c.load(name);
      const running=c[name]({name:'synthetic.mp4',size:10});
      if(phase==='metadata')c._authToken='second';
      video.onloadedmetadata();await new Promise(resolve=>setImmediate(resolve));
      if(phase==='response'){assert.equal(calls,1);c._authToken='second';release({ok:true,json:async()=>({file_id:'wrong-owner'})});}
      await running;
      assert.equal(calls,phase==='metadata'?0:1);
      assert.notEqual(c.diagState,'ready');assert.notEqual(c.genState,'done');
    }
  });
}
test('partial score remains unavailable; full score and escaped originals work',()=>{
  const c=context();c.load('_numOrNull','diagnosisDisplayScore','formatScoreValue','escapeHtml');
  assert.equal(c.diagnosisDisplayScore({composite_score:74,input_diagnostics:{score_scope:'partial_input'}}),null);
  assert.equal(c.formatScoreValue(null),'–');assert.equal(c.diagnosisDisplayScore({composite_score:74}),74);
  assert.equal(c.escapeHtml('<img src=x>'),'&lt;img src=x&gt;');
});
