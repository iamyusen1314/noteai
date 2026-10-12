// Offline tests of original HTML production functions; no account/provider calls.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../NoteAI_Pro_Demo_Framer.html'), 'utf8');
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script);
function source(name) {
  const match = new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(script);
  assert.ok(match, name);
  for (let end=script.indexOf('}',match.index);end>=0;end=script.indexOf('}',end+1)) {
    const value=script.slice(match.index,end+1);
    try {new vm.Script(value);return value;} catch {}
  }
  throw Error('Incomplete '+name);
}
function options(id) {
  const select = new RegExp('<select id="'+id+'"[\\s\\S]*?<\\/select>').exec(html)?.[0];
  assert.ok(select, id);
  return [...select.matchAll(/<option value="([^\"]*)"/g)].map(match=>({value:match[1]}));
}
test('all original industry selectors append leisure and preserve original order',()=>{
  for (const id of ['inputDomain','inputDomainSS','genDomain']) {
    assert.deepEqual(options(id).map(o=>o.value).filter(Boolean), ['美食','旅行','穿搭','美妆','家居','健身','母婴','休闲娱乐体验']);
  }
  assert.deepEqual(options('track-url-domain').map(o=>o.value),['美食','旅行','穿搭','运动','学习','职场','休闲娱乐体验']);
});
test('OCR category aliases and manual choice agree without guessing unknown content',()=>{
  const elements=Object.fromEntries(['inputDomain','inputDomainSS','genDomain'].map(id=>[id,{options:options(id),value:'美食'}]));
  const c=vm.createContext({document:{getElementById:id=>elements[id]}});
  for (const name of ['_supportedScreenshotDomain','syncDiagnosisDomain'])vm.runInContext(source(name),c);
  for (const category of ['洗浴','汤泉','水疗','按摩','SPA']) assert.equal(c._supportedScreenshotDomain(category),'休闲娱乐体验');
  assert.equal(c._supportedScreenshotDomain('未知'), '');
  c.syncDiagnosisDomain('休闲娱乐体验');
  assert.equal(elements.inputDomain.value,'休闲娱乐体验');assert.equal(elements.inputDomainSS.value,'休闲娱乐体验');
});
test('leisure merchant gate respects real names and hide policy',()=>{
  const c=vm.createContext({});
  for (const name of ['hasMerchantSignal','shouldAskMerchantBeforeRun'])vm.runInContext(source(name),c);
  for (const merchant of ['清风汤泉','清风水疗中心','清风洗浴中心','清风按摩馆']) assert.equal(c.hasMerchantSignal('休闲娱乐体验',merchant,'',''),true);
  assert.equal(c.shouldAskMerchantBeforeRun('休闲娱乐体验','','',{content_intent:'决策转化型',merchant_visibility:'show'}),true);
  assert.equal(c.shouldAskMerchantBeforeRun('休闲娱乐体验','','',{content_intent:'决策转化型',merchant_visibility:'hide'}),false);
});
test('missing leisure trend and benchmark display unknown instead of fabricated metrics',()=>{
  const elements=Object.fromEntries(['timingSourceMeta','timingEvidenceGrid','timingFormulaNote'].map(id=>[id,{style:{},textContent:'',innerHTML:''}]));
  const c=vm.createContext({document:{getElementById:id=>elements[id]},escapeHtml:value=>String(value),formatTimingCapture:()=> '未知'});
  vm.runInContext(source('renderMarketTimingEvidence'),c);
  c.renderMarketTimingEvidence({benchmark_available:false,benchmark_note:'暂无该行业表现基准。',data_stale:true,category_avg_ces:null,category_saturation:null});
  assert.match(elements.timingSourceMeta.innerHTML,/行业表现基准：暂无证据/);
  assert.equal((elements.timingEvidenceGrid.innerHTML.match(/暂无证据/g)||[]).length,3);
  assert.match(elements.timingFormulaNote.textContent,/暂无该行业表现基准/);
});
