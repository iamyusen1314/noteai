const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync(path.join(__dirname, '../model/admin.html'), 'utf8');
function source(name) {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match); return match[0];
}
test('cover Admin uses original reason/payload/idempotent POST contract', async () => {
  const submitted = [];
  const elements = {'mc-scope':{value:'test'},'cover-enabled':{checked:false},
    'cover-account-verified':{checked:true},'cover-execution-scope':{value:'acceptance'},'cover-evidence':{value:'receipt-fixture'}};
  const ctx = vm.createContext({document:{getElementById:id=>elements[id]},
    requireAdminCapability:()=>true, prompt:()=> 'offline fixture', confirm:()=>true, alert:()=>{},
    loadCoverConfig:async()=>{}, submitAdminOperation:async (...args)=>{submitted.push(args);return {request_id:'fixture'};}});
  new vm.Script('let _coverConfig={revision:4,active:{enabled:false},draft:{enabled:false,account_verified:true,execution_scope:"acceptance",account_evidence_ref:"receipt-fixture"}};'+source('changeCoverConfig')).runInContext(ctx);
  await ctx.changeCoverConfig('draft'); await ctx.changeCoverConfig('activate');
  assert.equal(submitted.length,2);
  for(const [url,body,...rest] of submitted) {
    assert.match(url,/^\/admin\/cover-config\/(draft|activate)$/);
    assert.equal(rest.length,0); assert.equal(body.reason,'offline fixture');
    assert.equal(body.payload.expected_revision,4); assert.equal(body.payload.scope,'test');
  }
  assert.equal(submitted[0][1].payload.config.account_evidence_ref,'receipt-fixture');
  assert.equal(submitted[1][1].payload.config,null);
});
test('cover Admin cannot submit without existing model configuration capability', async () => {
  const ctx=vm.createContext({requireAdminCapability:()=>false,submitAdminOperation:()=>assert.fail('denied')});
  new vm.Script('let _coverConfig={revision:0};'+source('changeCoverConfig')).runInContext(ctx);
  await ctx.changeCoverConfig('activate');
});
test('actual Admin scripts parse with added cover controls',()=>{
  for(const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new vm.Script(script[1]);
});
