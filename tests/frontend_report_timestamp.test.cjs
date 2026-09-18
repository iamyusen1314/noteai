const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
process.env.TZ='Asia/Shanghai';
const html=fs.readFileSync(path.join(__dirname,'..','NoteAI_Pro_Demo_Framer.html'),'utf8');
function source(name){const start=html.search(new RegExp('^(?:async )?function '+name+'\\(','m'));assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n}',start)+2);}
class FixedDate extends Date {constructor(...args){super(...(args.length?args:['2026-11-22T12:00:00Z']));}}
function fixture(result={}){
  const nodes=new Map(),painted=[];let downloads=0;
  const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',style:{},classList:{contains:()=>true}});return nodes.get(id);};
  const gradient={addColorStop(){}};
  const ctx=new Proxy({fillText:(text,x,y)=>painted.push({text,x,y}),createLinearGradient:()=>gradient,createRadialGradient:()=>gradient},{get:(target,key)=>target[key]??(()=>{})});
  const c=vm.createContext({Date:FixedDate,console,_diagnoseResult:result,_generateResult:null,_isGenerateMode:false,_historyReportSelection:null,
    document:{getElementById:node,body:{appendChild(){}},createElement:tag=>tag==='canvas'?{getContext:()=>ctx,toBlob:callback=>callback({})}:{click(){downloads++;},remove(){}}},
    gradeInfo:()=>({text:'有效评分'}),showToast(){},File:class{},navigator:{},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout:callback=>callback(),
  });
  vm.runInContext(['_fmtLocalTime','reportRecordedTime','reportTimeLabel','renderDiagnosisMetadata','renderDiagnosisHeader','renderGenerationHeader','completeProductResult','reportDiagnosisResult','syncFreshReportRecordedTime','shareDiagnosisCard'].map(source).join('\n'),c);
  return {c,node,painted,downloads:()=>downloads};
}
test('historical report metadata and header use its stored timestamp, never the viewing date',()=>{
  const d={created_at:'2026-09-12T09:31:00Z',note_title:'历史报告',_domain:'美食',composite_score:70};const f=fixture(d);
  f.c.renderDiagnosisMetadata(d);f.c.renderDiagnosisHeader(d);
  assert.match(f.node('reportMeta').textContent,/报告记录时间 2026-09-12 17:31/);
  assert.match(f.node('detail-meta').textContent,/报告记录时间 2026-09-12 17:31/);
  assert.doesNotMatch(f.node('reportMeta').textContent,/2026-11-22/);
});
test('a newly completed result uses the supplied record time and preserves local timezone conversion',()=>{
  const f=fixture();assert.equal(f.c.reportTimeLabel({created_at:'2026-11-22T11:20:00Z'}),'报告记录时间 2026-11-22 19:20');
  assert.equal(f.c.reportTimeLabel({created_at:'2026-09-12T23:31:00-05:00'}),'报告记录时间 2026-09-13 12:31');
});
test('missing or invalid timestamps remain explicitly unrecorded, not today or NaN',()=>{
  const f=fixture();for(const created_at of [undefined,null,'','invalid','2026-99-12T09:00:00Z',0,{},'0'])assert.equal(f.c.reportTimeLabel({created_at}),'报告时间未记录');
});
test('fresh diagnosis obtains only an exact type-and-report-ID date from the existing history response',()=>{
  const result={diagnosis_id:'diag-a',note_title:'同名笔记',composite_score:75};const f=fixture(result);
  assert.equal(f.c.syncFreshReportRecordedTime([{report_type:'analyze',report_id:'other',created_at:'2026-11-21T12:00:00Z'},{report_type:'analyze',report_id:'diag-a',created_at:'2026-11-22T10:00:00Z'}]),true);
  assert.equal(result.created_at,'2026-11-22T10:00:00Z');assert.match(f.node('reportMeta').textContent,/2026-11-22 18:00/);assert.equal(result.composite_score,75);
});
test('mismatching, missing and ambiguous history dates cannot be attached to the current result',()=>{
  const row={report_type:'analyze',report_id:'diag-a',created_at:'2026-09-12T09:31:00Z'};
  for(const rows of [[{...row,report_type:'generate'}],[{...row,report_id:'other'}],[{...row,created_at:null}],[row,row],[]]){
    const result={diagnosis_id:'diag-a'},f=fixture(result);assert.equal(f.c.syncFreshReportRecordedTime(rows),false);assert.equal(result.created_at,undefined);
  }
});
test('a valid original date and explicitly selected history are never overwritten',()=>{
  const row={report_type:'analyze',report_id:'diag-a',created_at:'2026-11-22T10:00:00Z'};
  const existing={diagnosis_id:'diag-a',created_at:'2026-09-12T09:31:00Z'},a=fixture(existing);assert.equal(a.c.syncFreshReportRecordedTime([row]),false);assert.equal(existing.created_at,'2026-09-12T09:31:00Z');
  const fresh={diagnosis_id:'diag-a'},b=fixture(fresh);b.c._historyReportSelection={report_type:'analyze',report_id:'old'};assert.equal(b.c.syncFreshReportRecordedTime([row]),false);assert.equal(fresh.created_at,undefined);
});
test('incomplete, failed and unknown results do not acquire a completion date',()=>{
  for(const flag of ['_error','_outcome_unknown','_waiting_for_input']){
    const result={diagnosis_id:'diag-a',[flag]:true},f=fixture(result);assert.equal(f.c.syncFreshReportRecordedTime([{report_type:'analyze',report_id:'diag-a',created_at:'2026-09-12T09:31:00Z'}]),false);assert.equal(result.created_at,undefined);
  }
});
test('generation uses the server generation receipt ID, never a saved-note or other-operation guess',()=>{
  const row={report_type:'generate',report_id:'server-request-a',created_at:'2026-11-22T10:00:00Z'};
  for(const billing of [{operation:'generate',request_id:'server-request-a'},{operation:'analyze',request_id:'server-request-a'},undefined]){
    const result={saved_note_id:'server-request-a',billing,_domain:'旅行'},f=fixture();f.c._isGenerateMode=true;f.c._generateResult=result;
    const expected=billing?.operation==='generate';assert.equal(f.c.syncFreshReportRecordedTime([row]),expected);
    if(expected){assert.equal(result.created_at,row.created_at);assert.match(f.node('reportMeta').textContent,/报告记录时间 2026-11-22 18:00/);}else assert.equal(result.created_at,undefined);
  }
});
test('leaving the report may cache its exact date but cannot change the visible page',()=>{
  const result={diagnosis_id:'diag-a'},f=fixture(result);f.node('page-report').classList.contains=()=>false;f.node('reportMeta').textContent='untouched';
  assert.equal(f.c.syncFreshReportRecordedTime([{report_type:'analyze',report_id:'diag-a',created_at:'2026-09-12T09:31:00Z'}]),true);assert.equal(f.node('reportMeta').textContent,'untouched');
});
for(const [created_at,wanted] of [['2026-09-12T09:31:00Z','报告记录时间 2026-09-12 17:31'],[null,'报告时间未记录']]){
  test('share card labels the report date: '+wanted,async()=>{
    const f=fixture({created_at,composite_score:75,_domain:'美食'}),button={textContent:'生成分享卡',disabled:false};await f.c.shareDiagnosisCard(button);
    assert.equal(f.painted.find(row=>row.x===88&&row.y===1340).text,wanted);assert.equal(f.downloads(),1);assert.equal(button.disabled,false);assert.equal(button.textContent,'生成分享卡');
  });
}
