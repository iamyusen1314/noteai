// Synthetic VM verification of the real FI1 usage UI block; no server or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../NoteAI_Pro_Demo_Framer.html'), 'utf8');
const start = html.indexOf('let _billingUsageReadSequence = 0;');
const end = html.indexOf('/* 复用正式订单、原价与同一权益入账链。 */', start);
assert.ok(start >= 0 && end > start, 'integrated billing block has exact boundaries');
const code = html.slice(start, end);
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
new vm.Script(scripts); // Detect syntax errors and duplicate lexical declarations when applied.

function defer() { let resolve, reject; const promise = new Promise((r, j) => {resolve=r; reject=j;}); return {promise, resolve, reject}; }
function tick() { return new Promise(resolve => setImmediate(resolve)); }
function element() {
  let text='', markup='';
  return {style:{}, nextElementSibling:{textContent:''},
    get textContent() {return text;}, set textContent(value) {text=String(value); markup='';},
    get innerHTML() {return markup;}, set innerHTML(value) {markup=String(value); text='';}};
}
function plan() {return {tier:'pro', tier_name:'创作套餐', price:99, monthly_credits:260, monthly_credits_used:25,
  monthly_credits_remaining:235, wallet_credits_balance:17, total_available_credits:252,
  period_start:'1900-01-01', expires_at:'1900-01-02', credit_policy:'周期积分优先，不足扣钱包',
  operation_costs:{analyze:{label:'诊断',credits:7.25,unit:'request'},generate:{label:'生成',credits:9.5,unit:'request'},
    chat_fast:{label:'对话',credits:1.75,unit:'request'},video_analyze:{label:'视频辅助理解',credits:0,included_in:['analyze','generate']}}};}
function usage() {return {
  window:{kind:'calendar_month',timezone:'UTC',start:'2026-09-01T00:00:00+00:00',end:'2026-10-01T00:00:00+00:00',as_of:'2026-09-19T03:14:15Z',basis:'usage_record_started_at'},
  subscription_period:{kind:'stored_subscription_period',start:'2026-08-28T10:20:30Z',end:'2026-09-27T10:20:30Z',timezone:'UTC'},
  accounting:{business:{recorded:7,completed:2,failed:1,refunded:0,waiting_for_input:1,running:1,status_unknown:2},
    auxiliary:{recorded:3,included_in_parent:3},models:{usage_records:20,without_physical_binding:0,pricing_or_usage_incomplete:2},
    physical:{recorded:22,responded:19,in_flight:1,unknown:2,usage_missing:1,not_dispatched_or_unconfirmed:0,count_basis:'public_trial_call_reservations',actual_http_requests:null},
    internal_model_steps:{by_step:{video_audio_understanding:1},without_step_metadata:2},local_steps:{status:'not_recorded',by_step:{},provider_http_requests:0},
    cost:{known_calculated_rmb:1.23,estimated_only_rmb:.45,unknown_records:2,complete:false,basis:'provider_usage_times_recorded_price',supplier_bill_paid_rmb:null}},
  total_tokens:2000,total_credits:14.5,total_api_cost:987654,
  by_operation:{analyze:{label:'AI诊断',kind:'business_operation',count:7,count_basis:'usage_records',total_tokens:2000,credits_used:14.5,cost_rmb:999999,
    status_counts:{completed:2,failed:1,waiting_for_input:1,running:1,status_unknown:2},known_calculated_rmb:1.23,manual_cost_rmb:0,estimated_only_rmb:.45,cost_complete:false,cost_basis:'legacy_mixed_estimate_and_usage_calculation',included_in_parent_records:0,physical_records:22,model_usage_records:20},
    video_analyze:{label:'视频辅助理解',kind:'auxiliary_event',count:3,count_basis:'usage_records',credits_used:0,cost_rmb:888888,
      status_counts:{},known_calculated_rmb:0,manual_cost_rmb:0,estimated_only_rmb:0,cost_complete:true,cost_basis:'legacy_mixed_estimate_and_usage_calculation',included_in_parent_records:3,physical_records:0,model_usage_records:0}},
  recent_records:[{label:'原视频诊断',operation:'analyze',kind:'business_operation',recorded_at:'2026-09-19T03:00:00Z',source:'mixed',
    credits_used:7.25,monthly_credits_used:5,wallet_credits_used:2.25,request_id:'task-original',total_tokens:2000,cost_rmb:765432,
    cost_mode:'actual',model_detail_count:1}],
};}
function fixture() {
  const nodes = new Map();
  const get = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  get('profile-usage-detail').style.display='none';
  const requests=[];
  const c = vm.createContext({console,Promise,Date,Number,Object,Array,Math,
    _authToken:'token-A',_authUser:{id:'A'},epoch:0,API_AUTH:'https://synthetic.invalid',
    document:{getElementById:get},escapeHtml:value=>String(value).replace(/[&<>"']/g,v=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[v])),
    fmtTokens:n=>String(n),refreshCreditBalance:async()=>plan(),
    fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>usage()};},
  });
  c.window=c;
  c._chatIdentitySnapshot=()=>({id:c._authUser.id,token:c._authToken,epoch:c.epoch});
  c._chatIdentityMatches=s=>s.id===c._authUser.id && s.token===c._authToken && s.epoch===c.epoch;
  vm.runInContext(code,c);
  const rendered=()=>[...nodes.values()].map(n=>n.innerHTML+n.textContent+n.nextElementSibling.textContent).join('\n');
  return {c,get,nodes,requests,rendered};
}

test('calendar-month request and actual UTC window stay separate from paid rights period',async()=>{
  const f=fixture();assert.equal(await f.c.loadBillingPlan(),true);
  assert.equal(f.requests[0].url,'https://synthetic.invalid/billing/usage?period=calendar_month');
  assert.equal(f.requests[0].options.headers.Authorization,'Bearer token-A');
  assert.ok(!f.requests[0].options.method || f.requests[0].options.method==='GET');
  const text=f.get('profile-plan-info').innerHTML;
  for(const item of ['本月 UTC 自然月','2026-09-01 00:00:00','2026-10-01 00:00:00','2026-09-19 03:14:15','当前已记录权益周期','2026-08-28 10:20:30','2026-09-27 10:20:30'])assert.ok(text.includes(item),item);
  assert.ok(!text.includes('1900-01-01'));
});
test('business records, completion, physical calls and local steps have distinct truthful units',async()=>{
  const f=fixture();await f.c.loadBillingPlan();const text=f.rendered();
  for(const item of ['业务记录','7 条','完成 2','供应商请求预留记录','22 条','结果未知 2','实际 HTTP 请求次数 待核','视频音画理解：1 条记录','未记录，不能据此判断未执行','没有独立日志，不显示为 0 次'])assert.ok(text.includes(item),item);
  assert.ok(!text.includes('0次表示本月尚未触发'));
  assert.ok(!text.includes('7次'));
});
test('known calculated and estimated costs remain distinct from unknown and paid supplier bills',async()=>{
  const f=fixture();await f.c.loadBillingPlan();const text=f.rendered();
  for(const item of ['已知计量 ¥1.2300','仅估算 ¥0.4500','待核 2 条','不是供应商账单实付','本月已知计量成本（非实付）'])assert.ok(text.includes(item),item);
  for(const old of ['987654','999999','888888','765432'])assert.ok(!text.includes(old),old);
});
test('auxiliary cost is explicitly included in parent rather than presented as an additive charge',async()=>{
  const f=fixture();await f.c.loadBillingPlan();const text=f.get('profile-usage-by-op').innerHTML;
  assert.ok(text.includes('计入主流程，勿重复相加'));assert.ok(text.includes('0.00积分'));
  assert.ok(f.get('profile-quota-bars').innerHTML.includes('已包含在主操作中，不单独扣分'));
});
test('nondefault server prices are preserved without an invented fallback or mutation',async()=>{
  const f=fixture(),p=plan();const before=JSON.stringify(p);f.c.refreshCreditBalance=async()=>p;await f.c.loadBillingPlan();
  const text=f.get('profile-quota-bars').innerHTML;
  for(const amount of ['7.25积分','9.5积分','1.75积分'])assert.ok(text.includes(amount));
  assert.equal(JSON.stringify(p),before);
  delete p.operation_costs;await f.c.loadBillingPlan();assert.ok(f.get('profile-quota-bars').innerHTML.includes('扣分待核'));
  assert.ok(!f.get('profile-quota-bars').innerHTML.includes('6积分'));
});
test('null, missing, empty, boolean and numeric strings do not become zero or known cost',()=>{
  const {c}=fixture();for(const value of [null,undefined,'',false,'0',NaN,-1])assert.equal(c.billingUsageValue(value),'待核');
  assert.equal(c.billingUsageValue(0),'0');assert.equal(c.billingUsageCost(null),'成本待核');
  assert.ok(c.billingUsageCost({known_calculated_rmb:null,unknown_records:null,complete:false}).includes('待核'));
});
test('documented sparse status counts use zero only within a present status map',async()=>{
  const f=fixture(),u=usage();u.by_operation.analyze.status_counts={completed:2};
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.ok(f.get('profile-usage-by-op').innerHTML.includes('完成 2 · 失败 0 · 已退回 0 · 待补充 0 · 处理中 0 · 状态待核 0'));
  delete u.by_operation.analyze.status_counts;await f.c.loadBillingPlan();
  assert.ok(f.get('profile-usage-by-op').innerHTML.includes('完成 待核 · 失败 待核'));
});
test('gift or extended rights display stored dates without claiming a 30-day entitlement',async()=>{
  const f=fixture(),u=usage();u.subscription_period.end='2027-01-12T06:00:00Z';
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  const text=f.get('profile-plan-info').innerHTML;
  assert.ok(text.includes('2027-01-12 06:00:00'));assert.ok(!text.includes('30天'));assert.ok(!text.includes('30 天'));
});
test('manual and estimated cost are labelled independently while platform total remains unreconciled',async()=>{
  const f=fixture(),u=usage();u.accounting.cost.manual_cost_rmb=2.34;u.accounting.cost.platform_total_rmb=null;
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.ok(f.rendered().includes('人工登记 ¥2.3400'));assert.ok(f.rendered().includes('平台总成本待核'));
  assert.ok(f.get('profile-cost-total').textContent.startsWith('¥1.2300'));
  assert.ok(!f.get('profile-cost-total').textContent.includes('3.5700'));
});
test('unrecognized operation count basis does not relabel legacy count as business executions',async()=>{
  const f=fixture(),u=usage();u.by_operation.analyze.count_basis='legacy_assumed_calls';
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.ok(f.get('profile-usage-by-op').innerHTML.includes('记录口径待核'));
  assert.ok(!f.get('profile-usage-by-op').innerHTML.includes('7 条记录'));
});
test('missing monthly totals or records retain unknown displays',async()=>{
  const f=fixture(),u=usage(),p=plan();delete u.total_tokens;delete u.total_credits;u.recent_records=null;
  p.monthly_credits=null;p.monthly_credits_used=null;p.monthly_credits_remaining=null;p.wallet_credits_balance=null;p.total_available_credits=null;
  f.c.refreshCreditBalance=async()=>p;f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.equal(f.get('profile-token-total').textContent,'待核');assert.equal(f.get('profile-credits-used-total').textContent,'待核');
  assert.equal(f.get('profile-credits-bal').textContent,'待核');assert.equal(f.get('profile-usage-recent').innerHTML,'最近记录待核');
});
test('confirmed empty records and zero known costs are distinguishable from missing logs',async()=>{
  const f=fixture(),u=usage();u.by_operation={};u.recent_records=[];u.accounting.cost={known_calculated_rmb:0,estimated_only_rmb:0,unknown_records:0,complete:true};
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.ok(f.get('profile-cost-total').textContent.includes('0.0000'));
  assert.ok(f.get('profile-usage-by-op').innerHTML.includes('不代表内部步骤未执行'));
});
test('recent receipt retains net credits, original cycle/wallet split and refund amount',async()=>{
  const f=fixture(),u=usage();u.recent_records.push({...u.recent_records[0],source:'refunded',credits_used:0,monthly_credits_used:0,wallet_credits_used:0,refunded_credits:7.25,request_id:'task-refunded'});
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();const text=f.get('profile-usage-recent').innerHTML;
  for(const item of ['周期 5.00 / 钱包 2.25','净扣 7.25','task-original','净扣 0.00 · 已退 7.25','task-refunded'])assert.ok(text.includes(item),item);
});
test('mixed receipt missing split is unknown while a recorded zero remains zero',async()=>{
  const f=fixture(),u=usage();u.recent_records[0].monthly_credits_used=null;u.recent_records[0].wallet_credits_used=0;
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();const text=f.get('profile-usage-recent').innerHTML;
  assert.ok(text.includes('周期 待核 / 钱包 0.00'));assert.ok(text.includes('净扣 7.25'));assert.ok(text.includes('待核'));
});
test('partial local scoring logs do not replace or erase model step reservations',async()=>{
  const f=fixture(),u=usage();u.accounting.local_steps={status:'partially_recorded',by_step:{local_score:{succeeded:3,failed:1}},provider_http_requests:0};
  f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();const text=f.get('profile-quota-bars').innerHTML;
  assert.ok(text.includes('本地评分：成功 3 条，失败 1 条'));assert.ok(text.includes('仅部分步骤有记录'));
  assert.ok(text.includes('视频音画理解：1 条记录'));assert.ok(text.includes('供应商请求预留记录'));assert.ok(text.includes('22 条'));
  assert.ok(text.includes('实际 HTTP 请求次数 待核'));
});
test('labels and request IDs are escaped, including incomplete supplier metadata',async()=>{
  const f=fixture(),u=usage(),p=plan();p.tier_name='<img src=x>';u.by_operation.analyze.label='<script>x</script>';u.recent_records[0].request_id='<svg onload=x>';
  f.c.refreshCreditBalance=async()=>p;f.c.fetch=async()=>({ok:true,json:async()=>u});await f.c.loadBillingPlan();
  assert.ok(!f.rendered().includes('<img src=x>'));assert.ok(!f.rendered().includes('<script>x</script>'));assert.ok(!f.rendered().includes('<svg onload=x>'));
  assert.ok(f.rendered().includes('&lt;svg onload=x&gt;'));
});
test('refresh clears stale expanded detail before waiting and repaints it after success',async()=>{
  const f=fixture();await f.c.loadBillingPlan();f.c.toggleUsageDetail();const delayed=defer();f.c.fetch=async()=>delayed.promise;
  const next=f.c.loadBillingPlan();await tick();assert.equal(f.c._lastUsageData,null);assert.equal(f.get('profile-usage-detail').style.display,'block');
  assert.ok(!f.get('profile-usage-recent').innerHTML.includes('task-original'));assert.match(f.get('profile-usage-recent').textContent,/正在核实/);
  const fresh=usage();fresh.recent_records[0].request_id='task-fresh';delayed.resolve({ok:true,json:async()=>fresh});await next;
  assert.ok(f.get('profile-usage-recent').innerHTML.includes('task-fresh'));
});
test('503 clears prior data and displays a visible retry instruction',async()=>{
  const f=fixture();await f.c.loadBillingPlan();f.c.fetch=async()=>({ok:false,status:503});assert.equal(await f.c.loadBillingPlan(),false);
  assert.equal(f.c._lastUsageData,null);assert.equal(f.get('profile-cost-total').textContent,'待核');assert.match(f.get('profile-usage-recent').textContent,/读取失败.*重试/);
  assert.ok(!f.rendered().includes('task-original'));
});
test('legacy rolling-window response is rejected rather than silently called this month',async()=>{
  const f=fixture();f.c.fetch=async()=>({ok:true,json:async()=>({total_api_cost:0,total_tokens:0,by_operation:{}})});
  assert.equal(await f.c.loadBillingPlan(),false);assert.equal(f.c._lastUsageData,null);assert.match(f.get('profile-plan-info').textContent,/读取失败/);
});
test('same-account slower JSON cannot overwrite the later request',async()=>{
  const f=fixture(),old=defer();let calls=0;f.c.fetch=async()=>({ok:true,json:()=>++calls===1?old.promise:Promise.resolve({...usage(),recent_records:[]})});
  const first=f.c.loadBillingPlan();await tick();assert.equal(await f.c.loadBillingPlan(),true);old.resolve(usage());assert.equal(await first,false);
  assert.equal(f.c._lastUsageData.recent_records.length,0);assert.ok(!f.rendered().includes('task-original'));
});
test('account A late success and failure cannot overwrite account B',async()=>{
  for(const fail of [false,true]){
    const f=fixture(),old=defer();f.c.fetch=async()=>old.promise;const a=f.c.loadBillingPlan();await tick();
    f.c._authToken='token-B';f.c._authUser={id:'B'};f.c.epoch++;f.c.resetBillingUsageState('待更新',true);
    const bUsage=usage();bUsage.recent_records[0].request_id='task-B';f.c.fetch=async()=>({ok:true,json:async()=>bUsage});await f.c.loadBillingPlan();
    if(fail)old.reject(new Error('late A'));else old.resolve({ok:true,json:async()=>usage()});assert.equal(await a,false);
    assert.ok(f.rendered().includes('task-B'));assert.ok(!f.rendered().includes('task-original'));assert.ok(!f.rendered().includes('读取失败'));
  }
});
test('identity guard runs again after parsing and denies cross-account cached repaint',async()=>{
  const f=fixture(),json=defer();f.c.fetch=async()=>({ok:true,json:()=>json.promise});const running=f.c.loadBillingPlan();await tick();
  f.c._authToken='token-B';f.c._authUser={id:'B'};f.c.epoch++;json.resolve(usage());assert.equal(await running,false);assert.equal(f.c._lastUsageData,null);
  f.c._lastUsageData=usage();f.c._billingUsageIdentity={id:'A',token:'token-A',epoch:0};f.get('profile-usage-recent').textContent='B boundary';f.c.renderUsageDetail();
  assert.equal(f.get('profile-usage-recent').textContent,'B boundary');
});
test('logout clears rendered private billing nodes and prevents pending resurrection',async()=>{
  const f=fixture();await f.c.loadBillingPlan();f.c.toggleUsageDetail();const old=defer();f.c.fetch=async()=>old.promise;const pending=f.c.loadBillingPlan();await tick();
  f.c._authToken=null;f.c.epoch++;f.c.resetBillingUsageState('待更新',true);old.resolve({ok:true,json:async()=>usage()});await pending;
  assert.equal(f.c._lastUsageData,null);assert.equal(f.get('profile-usage-detail').style.display,'none');assert.ok(!f.rendered().includes('task-original'));
});
