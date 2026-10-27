const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','NoteAI_Pro_Demo_Framer.html'),'utf8');
const native=fs.readFileSync(path.join(__dirname,'..','assets','payment-native.js'),'utf8');
const facts=html.slice(html.indexOf('let _productDisclosure = null;'),html.indexOf('async function refreshPublicStatus()'));
function response(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>data};}
function contract(overrides={}){return {
  version:'free-product-2026-09-12',acceptance_version:'free-product-2026-09-12',acceptance_record_policy:'historical_acceptances_unchanged_not_proof_of_current_runtime',
  disclosure_version:'product-disclosure-2026-09-19',observed_at:'2026-09-19T03:00:00+00:00',scope:'formal_product',payment_enabled:true,payment_status:'available',payment_providers:['wechatpay_direct'],payment_status_source:'local_payment_capabilities',
  privacy:{authentication_credentials_in_ai_context:false,ai_context_data:['submitted_creation_content','selected_media_or_media_observations','explicit_creator_preferences','current_task_context'],route_basis:'published_runtime_configuration_not_per_task_call_evidence',
    material_processing:'豆包境内理解图片、视频及原音轨；必要文本与适用偏好按已发布文字路由处理',
    model_routes:[{id:'doubao',name:'Doubao Seed 2.0 Lite 0428',group:'media_models',enabled:true},{id:'kimi',name:'Kimi K2.6',group:'generation_models',enabled:false},{id:'claude',name:'Claude Haiku / Sonnet',group:'generation_models',enabled:true}]},
  cross_border:{possible_route:'Alibaba_China_to_Claude_Gateway_Singapore',historical_acceptance_is_new_consent:false},
  retention:{free_active_hours:168,free_recovery_hours:168,rolling_backup_clear_within_days:30,paid_created_archives:'no_product_expiry_while_account_exists',downgrade_deletes_paid_archives:false},
  refund:{policy:'full_unused_entitlement_only',settlement:'original_channel_and_order_ledger_reconciliation',auto_renewal:false,amount_basis:'server_order_quote'},
  contact_verification:{phone_reset_supported:true,verified_email_recovery_fallback:false,email_status:'delivery_adapter_not_connected'},...overrides};}
function fixture(fetchReply=()=>response(contract()),withNative=false){
  const nodes=new Map(),calls=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{id,textContent:'',style:{},dataset:{},children:[],querySelector(){return null;},prepend(node){nodes.set(node.id,node);},append(node){nodes.set(node.id,node);},addEventListener(){}});return nodes.get(id);};
  get('public-auth-status').dataset.smsNotice='短信服务状态来自现有状态接口。';
  const c=vm.createContext({console,Date,API_BASE:'https://synthetic.invalid',_authToken:null,_authUser:null,
    navigator:{userAgent:'synthetic desktop'},authHeader:()=>({}),document:{getElementById:get,querySelectorAll:()=>[],createElement:()=>({style:{},addEventListener(){}})},
    fetch:async(url,options)=>{calls.push({url,options});return fetchReply(url,options);},
  });
  if(withNative)vm.runInContext(native,c);
  vm.runInContext(facts,c);
  return {c,get,calls,setNative(value,read=1){vm.runInContext('_nativeCapability='+JSON.stringify(value)+';_nativeCapabilityRead='+read,c);}};
}
test('current disclosure distinguishes version, historical acceptance, material and applicable AI context',async()=>{
  const f=fixture();await f.c.loadProductDisclosure();assert.equal(f.calls.length,1);assert.equal(f.calls[0].options.cache,'no-store');assert.match(f.get('legal-version').textContent,/product-disclosure-2026-09-19.*2026-09-19T03/);
  assert.match(f.get('legal-current-summary').textContent,/free-product-2026-09-12.*历史接受记录不证明当前运行状态/);
  const privacy=f.get('legal-privacy-facts').textContent;assert.match(privacy,/Claude Haiku \/ Sonnet/);assert.match(privacy,/Kimi K2.6（配置未开放）/);assert.match(privacy,/原音轨/);assert.match(privacy,/明确保存且适用的创作者偏好/);assert.match(privacy,/认证凭据不进入模型上下文/);assert.match(privacy,/新加坡/);assert.match(privacy,/不是单次任务实际调用证明/);
  assert.doesNotMatch(privacy,/账户信息不发送给模型|只使用境内 Kimi|仅使用Kimi/);
});
test('available formal payment explicitly describes Native, pending H5 and current refund policy',async()=>{
  const f=fixture();await f.c.loadProductDisclosure();const text=f.get('legal-refund-facts').textContent;
  assert.match(text,/Native 扫码支付当前可下单/);assert.match(text,/H5 已申请、待审核/);assert.match(text,/当前结算未开放微信内直接付款/);assert.match(text,/所购权益未消耗时，可申请全额原路退款/);assert.match(text,/申请不代表到账/);assert.match(text,/不自动续费/);assert.match(text,/服务端订单报价/);
  assert.doesNotMatch(text,/无条件|7天.*退款|比例退款|支付网关尚未启用|不得收取真实款项/);
});
test('JSAPI disclosure requires an explicit current capability and retains Native and H5 boundaries',()=>{
  const f=fixture(()=>response(contract()),true);
  const available={ordering_available:true,providers:['wechatpay_direct'],wechat_jsapi_available:true};
  const text=f.c.productPaymentDisclosureText(available);
  assert.match(text,/微信内可授权后直接付款/);assert.match(text,/电脑使用 Native 扫码/);
  assert.match(text,/H5 支付仍待审核/);assert.doesNotMatch(text,/JSAPI 尚未接入|当前结算未开放微信内直接付款/);
  for(const value of [null,{...available,wechat_jsapi_available:false},{...available,wechat_jsapi_available:undefined}]){
    assert.match(f.c.productPaymentDisclosureText(value),/当前结算未开放微信内直接付款/);
  }
});
test('known unavailable and unknown payment states remain different',async()=>{
  for(const [data,expected,forbidden] of [
    [contract({payment_enabled:false,payment_status:'unavailable',payment_providers:[]}),'不可下单','暂无法确认'],
    [contract({payment_enabled:null,payment_status:'unknown',payment_providers:null}),'暂无法确认','不可下单'],
  ]){const f=fixture(()=>response(data));await f.c.loadProductDisclosure();assert.match(f.get('public-pricing-notice').textContent,new RegExp(expected));assert.doesNotMatch(f.get('public-pricing-notice').textContent,new RegExp(forbidden));}
});
for(const [label,result] of [
  ['HTTP failure',()=>response({},503)],['HTML response',()=>({ok:true,status:200,json:async()=>{throw Error('HTML');}})],
  ['legacy version only',()=>response({version:'free-product-2026-09-12',refund:{real_payment_gateway_enabled:false}})],
  ['account-only scope',()=>response(contract({scope:'website_and_accounts'}))],['invalid observed date',()=>response(contract({observed_at:'not a date'}))],
])test(label+' is unknown current facts and never auto-retried',async()=>{
  const f=fixture(result);await f.c.loadProductDisclosure();await f.c.loadProductDisclosure();f.c.renderProductFacts();assert.equal(f.calls.length,1);assert.match(f.get('legal-version').textContent,/待核实/);assert.match(f.get('legal-refund-facts').textContent,/付款状态暂无法确认/);assert.match(f.get('legal-refund-facts').textContent,/退款条件尚未确认/);assert.doesNotMatch(f.get('legal-current-summary').textContent,/以下为已实现/);
});
for(const [label,cap] of [
  ['not yet known',null],['missing shape',{}],['contradictory available',{ordering_available:true,providers:[]}],['contradictory unavailable',{ordering_available:false,providers:['wechatpay_direct']}],['non-array providers',{ordering_available:true,providers:'wechatpay_direct'}],
])test('Native '+label+' cannot become closed or falsely available',()=>{
  const f=fixture();const text=f.c.productPaymentDisclosureText(cap);assert.match(text,/暂无法确认/);assert.doesNotMatch(text,/当前可下单|当前查询结果为不可下单/);
});
test('malformed legal payment tuple is unknown even when other disclosure fields are valid',async()=>{
  const f=fixture(()=>response(contract({payment_enabled:false,payment_status:'available',payment_providers:[]})));await f.c.loadProductDisclosure();assert.match(f.get('public-pricing-notice').textContent,/暂无法确认/);assert.match(f.get('legal-privacy-facts').textContent,/Claude/);
});
test('unknown refund enum or null is not substituted with the known full-refund rule',async()=>{
  for(const policy of [null,'new_unconfirmed_policy']){const f=fixture(()=>response(contract({refund:{policy}})));await f.c.loadProductDisclosure();assert.match(f.get('legal-refund-facts').textContent,/退款条件尚未确认/);assert.doesNotMatch(f.get('legal-refund-facts').textContent,/可申请全额/);}
});
test('Native confirmed capability is reused without another GET and canary is never public availability',async()=>{
  const f=fixture(()=>response(contract()),true);await f.c.loadProductDisclosure();f.setNative({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:{product_kind:'subscription',product_id:'synthetic'}});f.c.nativeSyncControls();
  assert.equal(f.calls.length,1);assert.match(f.get('public-pricing-notice').textContent,/仅本人授权/);assert.match(f.get('legal-refund-facts').textContent,/不能据此认定公众收款已开放/);assert.doesNotMatch(f.get('public-pricing-notice').textContent,/扫码支付当前可下单/);
});
test('failed newer Native capability does not fall back to old available legal payment fact',async()=>{
  const f=fixture(()=>response(contract()),true);await f.c.loadProductDisclosure();f.setNative(null);f.c.nativeSyncControls();assert.match(f.get('public-pricing-notice').textContent,/暂无法确认/);assert.match(f.get('legal-refund-facts').textContent,/暂无法确认/);assert.doesNotMatch(f.get('public-pricing-notice').textContent,/当前可下单|暂未开放/);
});
test('capability available for another provider cannot falsely advertise WeChat Native ordering',()=>{
  const f=fixture();const text=f.c.productPaymentDisclosureText({ordering_available:true,providers:['other_provider']});assert.doesNotMatch(text,/微信 Native 扫码支付当前可下单/);assert.match(text,/购买入口仍待核实/);
});
test('a canary for another provider cannot advertise authorized WeChat Native checkout',()=>{
  const f=fixture();const text=f.c.productPaymentDisclosureText({ordering_available:true,providers:['other_provider'],canary_checkout:{product_kind:'subscription',product_id:'synthetic'}});
  assert.match(text,/付款状态暂无法确认/);assert.doesNotMatch(text,/仅本人授权|自测订单可下单|扫码支付当前可下单/);
});
test('an empty or invalid canary cannot advertise authorization without its scoped product',()=>{
  const f=fixture();
  for(const canary_checkout of [{},true,{product_kind:'unknown',product_id:'synthetic'},{product_kind:'subscription',product_id:''}]){
    const text=f.c.productPaymentDisclosureText({ordering_available:true,providers:['wechatpay_direct'],canary_checkout});
    assert.match(text,/付款状态暂无法确认/);assert.doesNotMatch(text,/仅本人授权|自测订单可下单/);
  }
});
test('Native module remains compatible when current facts helpers are not present',()=>{
  const nodes=new Map([['public-pricing-notice',{textContent:''}],['pricing-content',null]]);const c=vm.createContext({document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>[]}});vm.runInContext(native,c);c.nativeSyncControls();assert.match(nodes.get('public-pricing-notice').textContent,/暂无法确认/);
});
test('auth disclosure states route risks without a new acceptance request or a fabricated email capability',async()=>{
  const f=fixture();await f.c.loadProductDisclosure();const text=f.get('public-auth-status').textContent;assert.match(text,/Claude文字/);assert.match(text,/适用偏好可能.*新加坡/);assert.match(text,/不视作新的单独跨境同意/);assert.equal(f.calls.length,1);assert(f.calls.every(call=>call.url.endsWith('/legal/contracts')));assert.match(f.get('legal-account-facts').textContent,/实际短信发送能力以当前服务状态为准/);assert.match(f.get('legal-account-facts').textContent,/邮箱验证码发送尚未接通/);
});
test('disclosure preserves existing acceptance identifier and payload boundaries',()=>{
  assert.match(html,/const PUBLIC_PRODUCT_CONTRACT = 'free-product-2026-09-12'/);
  const accept=html.slice(html.indexOf('async function acceptProductContract()'),html.indexOf('function completeProductResult('));
  assert.match(accept,/contract_version:PUBLIC_PRODUCT_CONTRACT,privacy_accepted:true/);assert.doesNotMatch(accept,/disclosure_version|cross_border_notice_acknowledged/);
  const otp=html.slice(html.indexOf('async function publicPhoneAuth()'),html.indexOf('/* ── Page System'));
  assert.doesNotMatch(otp,/cross_border_notice_acknowledged|disclosure_version/);
});
test('pre-fetch legal content does not display historical false current facts',()=>{
  const legal=html.slice(html.indexOf('id="page-legal"'),html.indexOf('</footer>'));
  assert.doesNotMatch(legal,/不收取真实款项|真实支付网关尚未启用|只使用境内 Kimi|账户信息不发送给模型/);assert.match(legal,/尚未确认|待核实/);
});
test('avatar grid changes are contained in original <=900 rule and remain content-sized',()=>{
  const block=html.slice(html.indexOf('@media(max-width:900px){'),html.indexOf('@media(max-width:560px){'));
  assert.match(block,/#avatar-picker-grid\{grid-template-columns:repeat\(auto-fit,minmax\(44px,1fr\)\)/);assert.match(block,/#avatar-picker-modal>div\{[^}]*overflow-y:auto/);assert.match(block,/#avatar-picker-grid>button\{[^}]*min-height:44px/);
});

test('legal payment availability without the confirmed local capability provenance remains unknown',async()=>{
  const f=fixture(()=>response(contract({payment_status_source:'historical_report'})));await f.c.loadProductDisclosure();assert.match(f.get('public-pricing-notice').textContent,/暂无法确认/);assert.doesNotMatch(f.get('public-pricing-notice').textContent,/当前可下单/);
});

test('failed disclosure does not erase independently confirmed Native payment availability',async()=>{
  const f=fixture(()=>response({},503),true);await f.c.loadProductDisclosure();f.setNative({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:null});f.c.nativeSyncControls();
  assert.match(f.get('legal-current-summary').textContent,/独立付款查询见下方/);assert.match(f.get('legal-refund-facts').textContent,/微信 Native 扫码支付当前可下单/);assert.match(f.get('legal-refund-facts').textContent,/退款条件尚未确认/);assert.match(f.get('legal-privacy-facts').textContent,/披露尚未确认/);assert.equal(f.calls.length,1);
});
