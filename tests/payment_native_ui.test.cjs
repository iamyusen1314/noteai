const fs=require('fs'), vm=require('vm'), assert=require('assert');
const root=__dirname+'/../assets', source=fs.readFileSync(root+'/payment-native.js','utf8'), vendor=fs.readFileSync(root+'/vendor/qrcode-generator-2.0.4.js','utf8');
const base={id:'11111111-1111-4111-8111-111111111111',product_kind:'credit_package',product_id:'starter',amount_fen:1200,provider_mode:'live',payment_status:'pending',entitlement_status:'pending',refund_status:'none',refunded_fen:0,created_at:'2026-09-14T00:00:00Z'};
function findAll(node,predicate){return (node.children||[]).flatMap(child=>[...(predicate(child)?[child]:[]),...findAll(child,predicate)]);}
const find=(node,predicate)=>findAll(node,predicate)[0];
const hasClass=(node,name)=>(node.className||'').split(/\s+/).includes(name);
const buttons=node=>findAll(node,e=>e.tagName==='BUTTON');
function make({renderDom=false}={}){const storage=new Map(),renders=[],dialogs=[],nodes=new Map(),timers=new Map();let nextTimer=0,billingReads=0;
 class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.style={};this.attributes={};this._text='';this.open=false;}
  get textContent(){return this._text+this.children.map(child=>child.textContent||'').join('');}
  set textContent(value){this._text=String(value);this.children=[];}
  append(...values){for(const child of values){child.parentNode=this;this.children.push(child);}}
  addEventListener(name,fn){this[name]=fn;}
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return this.attributes[name]??null;}
  querySelectorAll(selector){return findAll(this,e=>selector.startsWith('[')?Object.hasOwn(e.attributes,selector.slice(1,-1)):e.tagName===selector.toUpperCase());}
  getContext(kind){assert.equal(kind,'2d');return {fillStyle:'',fillRect(){}};}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(child=>child!==this);nodes.delete(this.id);}
  showModal(){this.open=true;nodes.set(this.id,this);}
 }
 const document={createElement:t=>new Element(t),getElementById:id=>nodes.get(id)||find(document.body,e=>e.id===id)||null,querySelectorAll:selector=>document.body.querySelectorAll(selector),body:new Element('body')};
 const c=vm.createContext({_authUser:{id:'owner-A'},_authToken:'synthetic-token-A',API_BASE:'https://offline.invalid',sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},document,setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id),crypto:{randomUUID:()=>base.id},authHeader:()=>({Authorization:'Bearer synthetic'}),requireProductConsent:()=>true,openAuthModal:()=>{},showToast:()=>{},loadBillingPlan:()=>billingReads++,fetch:()=>{throw Error('unexpected fetch');}});
 vm.runInContext(vendor,c);vm.runInContext(source,c);if(!renderDom){c.nativeDialog=(title,body)=>dialogs.push({title,body});c.nativeRenderOrder=value=>{if(value.user_id===c._authUser?.id)renders.push(value.order);};}return {c,storage,renders,dialogs,nodes,timers,get billingReads(){return billingReads;}};}
const json=x=>({ok:true,json:async()=>x});
const set=(c,name,value)=>{c.__value=value;vm.runInContext(name+'=__value',c);};
const value=()=>({user_id:'owner-A',product_kind:'credit_package',product_id:'starter',amount_fen:1200,key:'synthetic-native-original',canary:true,attempted:false});
(async()=>{const results=[];
 for (const [ua,expected] of [['Desktop Browser','desktop'],['iPhone Mobile','mobile'],['iPhone MicroMessenger','wechat']]) {
  const {c}=make();c.navigator={userAgent:ua};assert.equal(c.nativePaymentEnvironment(),expected);
  const hint=c.nativePaymentHint();assert.match(hint,/Native/);if(expected!=='desktop'){assert.match(hint,/不能在本机直接拉起/);assert.match(hint,/当前查询未确认微信内直接支付可用/);assert.doesNotMatch(hint,/JSAPI.{0,5}(尚未|未)接入/);}results.push('payment-environment-'+expected+' PASS');
 }

 {const {c,renders}=make(),v=value();v.attempted=true;v.order={...base};set(c,'_nativeCheckout',v);c.fetch=async()=>json({...base,payment_status:'succeeded',entitlement_status:'applied'});await c.nativeRecoverOriginal(false);assert.equal(v.order.payment_status,'succeeded');assert.equal(renders.length,1);results.push('plain-detail-response-readback PASS');}
 {const {c,storage}=make(),v=value();let posts=0;c.fetch=async(url,options)=>{if(options?.method==='POST'){posts++;throw Error('synthetic connection lost');}return json({orders:[]});};await c.nativeSubmitCheckout(v);await c.nativeSubmitCheckout(v);assert.equal(posts,1);assert.equal(JSON.parse(storage.get('noteai-native:owner-A')).attempted,true);results.push('UNKNOWN-double-submit-one-POST PASS');}
 {const {c,renders}=make(),v=value();let release,posts=0;c.fetch=(url,options)=>{if(options?.method==='POST'){posts++;throw Error('must not post');}return new Promise(r=>release=r);};const pending=c.nativeSubmitCheckout(v);c.nativeClearSession();c._authUser={id:'owner-B'};c._authToken='synthetic-token-B';release(json({orders:[]}));await pending;assert.equal(posts,0);assert.equal(renders.length,0);results.push('account-switch-before-dispatch-no-POST PASS');}
 {const {c,renders}=make(),v=value();let release;c.fetch=async(url,options)=>options?.method==='POST'?await new Promise(r=>release=r):json({orders:[]});const pending=c.nativeSubmitCheckout(v);while(!release)await Promise.resolve();c.nativeClearSession();c._authUser={id:'owner-B'};c._authToken='synthetic-token-B';release(json({order:{...base},checkout:JSON.stringify({channel:'wechatpay_native',kind:'qr_text',value:'weixin://wxpay/bizpayurl?pr=SyntheticOnly'})}));await pending;assert.equal(renders.length,0);results.push('account-switch-after-dispatch-no-old-account-display PASS');}
 {const {c}=make();const pending=c.nativeOrderState({...base,payment_status:'succeeded',entitlement_status:'applied',refund_status:'pending'});const manual=c.nativeOrderState({...base,payment_status:'succeeded',entitlement_status:'applied',refund_status:'needs_manual'});assert.equal(pending.terminal,false);assert.match(pending.text,/退款处理中/);assert.equal(manual.terminal,true);assert.match(manual.text,/退款结果需要核实/);results.push('refund-pending-and-manual-truthful PASS');}
 {const {c,storage}=make(),original={...value(),attempted:true};c.nativeSaveStorage(original);const history={user_id:'owner-A',order:{...base,id:'22222222-2222-4222-8222-222222222222',product_id:'creator',amount_fen:3900,payment_status:'succeeded',entitlement_status:'applied'},amount_fen:3900,key:'',attempted:true};set(c,'_nativeCheckout',history);c.fetch=async()=>json(history.order);await c.nativeRecoverOriginal(false);const saved=JSON.parse(storage.get('noteai-native:owner-A'));assert.equal(saved.key,original.key);assert.equal(saved.product_id,'starter');results.push('read-only-history-preserves-UNKNOWN-key PASS');}
 {const {c,storage,dialogs}=make(),original={...value(),canary:false,attempted:true};c.nativeSaveStorage(original);let posts=0,reads=0;c.fetch=async(url,opt)=>{if(opt?.method==='POST'){posts++;throw Error('must not post');}if(url.endsWith('/payments/capabilities'))return json({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:null});if(url.endsWith('/billing/tiers'))return json({topup_packages:[{id:'creator',name:'Synthetic creator',price_rmb:39}]});if(url.endsWith('/payments/orders')){reads++;return json({orders:[]});}throw Error('unexpected URL');};await c.nativeStartCheckout('credit_package','creator');assert.equal(posts,0);assert.equal(reads,1);assert.equal(dialogs.length,0);assert.equal(JSON.parse(storage.get('noteai-native:owner-A')).key,original.key);results.push('different-product-UNKNOWN-no-new-order PASS');}
 {const {c,dialogs}=make();let release,catalogs=0;c.fetch=async(url)=>{if(url.endsWith('/payments/capabilities'))return await new Promise(r=>release=r);catalogs++;throw Error('unexpected subsequent fetch');};const pending=c.nativeStartCheckout('credit_package','starter');c.nativeClearSession();c._authUser={id:'owner-B'};c._authToken='synthetic-token-B';release(json({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:null}));await pending;assert.equal(catalogs,0);assert.equal(dialogs.length,0);results.push('account-switch-during-capability-read-stops-preparation PASS');}
 {const {c,dialogs}=make();let release;c.fetch=async(url)=>url.endsWith('/payments/capabilities')?json({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:null}):await new Promise(r=>release=r);const pending=c.nativeStartCheckout('credit_package','starter');while(!release)await Promise.resolve();c.nativeClearSession();c._authUser={id:'owner-B'};c._authToken='synthetic-token-B';release(json({topup_packages:[{id:'starter',name:'Synthetic starter',price_rmb:12}]}));await pending;assert.equal(dialogs.length,0);results.push('account-switch-during-catalog-read-stops-preparation PASS');}
 {const {c}=make();const qr=c.qrcode(0,'M');qr.addData('weixin://wxpay/bizpayurl?pr=SyntheticOnly','Byte');qr.make();assert.ok(qr.getModuleCount()>20);assert.equal(typeof qr.isDark(0,0),'boolean');results.push('local-vendor-synthetic-QR-matrix PASS');}
 for(const scenario of ['refunded-new','closed-new','same-key','paid','pending','partial','unreversed','no-canary','empty-key','read-failed','read-busy']) {
  const {c,storage,dialogs}=make();
  const order={...base,payment_status:'succeeded',entitlement_status:'reversed',refund_status:'refunded',refunded_fen:1200};
  if(scenario==='closed-new')Object.assign(order,{payment_status:'closed',entitlement_status:'pending',refund_status:'none',refunded_fen:0});
  if(scenario==='paid')Object.assign(order,{entitlement_status:'applied',refund_status:'none',refunded_fen:0});
  if(scenario==='pending')order.refund_status='pending';
  if(scenario==='partial')order.refunded_fen=600;
  if(scenario==='unreversed')order.entitlement_status='applied';
  const original={...value(),attempted:true,order};c.nativeSaveStorage(original);
  if(scenario==='read-busy')set(c,'_nativeReadBusy',true);
  const canary={product_kind:'credit_package',product_id:'starter',amount_fen:1200,idempotency_key:scenario==='same-key'?original.key:scenario==='empty-key'?'':'synthetic-new-activation'};
  let posts=0;
  c.fetch=async(url,opt)=>{
   if(opt?.method==='POST'){posts++;throw Error('no automatic submission');}
   if(url.endsWith('/payments/capabilities'))return json({ordering_available:true,providers:['wechatpay_direct'],canary_checkout:scenario==='no-canary'?null:canary});
   if(url.endsWith('/billing/tiers'))return json({topup_packages:[{id:'starter',name:'Synthetic starter',price_rmb:12}]});
   if(url.endsWith('/payments/orders/'+base.id)){if(scenario==='read-failed')throw Error('unavailable');return json(order);}
   throw Error('unexpected URL');
  };
  await c.nativeStartCheckout('credit_package','starter');
  const allowed=['refunded-new','closed-new','no-canary'].includes(scenario);
  assert.equal(dialogs.filter(d=>d.title==='确认付款').length,allowed?1:0,scenario);
  assert.equal(posts,0,scenario);assert.equal(JSON.parse(storage.get('noteai-native:owner-A')).key,original.key,scenario);
  results.push('canary-original-'+scenario+' PASS');
 }
 {const {c,nodes}=make({renderDom:true}),v={...value(),method:'native',display_name:'30积分充值',display_credits:30};let submits=0;c.nativeSubmitCheckout=received=>{assert.equal(received,v);submits++;};c.nativeShowConfirmation(v);
  const dialog=nodes.get('native-checkout-dialog'),body=dialog.children[1],action=find(body,e=>hasClass(e,'native-pay-actions'));
  assert.equal(dialog.children[0].textContent,'确认付款');assert.equal(dialog.getAttribute('aria-labelledby'),dialog.children[0].id);assert.equal(body.className,'native-pay-main');assert.equal(submits,0);
  assert.match(body.textContent,/30积分/);assert.match(body.textContent,/12\.00/);assert.match(body.textContent,/微信支付/);assert.equal(find(body,e=>e.tagName==='DETAILS').open,false);
  const button=find(action,e=>e.tagName==='BUTTON');assert.equal(button.textContent,'生成支付二维码');await button.click();assert.equal(submits,1);results.push('native-confirmation-nested-explicit-action PASS');
 }
 for(const [name,patch,title,credited] of [
  ['paid-entitlement-pending',{payment_status:'succeeded'},'支付已确认',false],
  ['paid-applied',{payment_status:'succeeded',entitlement_status:'applied'},'支付成功',true],
  ['refund-pending',{payment_status:'succeeded',entitlement_status:'applied',refund_status:'pending'},'退款处理中',false],
  ['refund-manual',{payment_status:'succeeded',entitlement_status:'applied',refund_status:'needs_manual'},'结果需要核实',false],
  ['refund-full',{payment_status:'succeeded',entitlement_status:'reversed',refund_status:'refunded',refunded_fen:1200},'已全额退款',false],
  ['refund-partial',{payment_status:'succeeded',entitlement_status:'applied',refund_status:'refunded',refunded_fen:600},'退款结果待核实',false],
  ['payment-manual',{payment_status:'needs_manual'},'结果需要核实',false],
  ['entitlement-manual',{payment_status:'succeeded',entitlement_status:'needs_manual'},'结果需要核实',false],
  ['closed',{payment_status:'closed'},'订单已关闭',false],
  ['failed',{payment_status:'failed'},'支付未成功',false]
 ]){
  const {c,nodes,timers}=make({renderDom:true}),v={...value(),attempted:true,checkout:'weixin://wxpay/bizpayurl?pr=SyntheticOnly',display_credits:30,order:{...base,...patch}};c.nativeRenderOrder(v);
  const dialog=nodes.get('native-checkout-dialog'),body=dialog.children[1];assert.equal(dialog.children[0].textContent,'支付结果',name);assert.equal(find(body,e=>e.tagName==='H3').textContent,title,name);
  assert.equal(findAll(body,e=>e.tagName==='CANVAS').length,0,name);assert.equal(buttons(body).some(e=>['微信支付','生成支付二维码'].includes(e.textContent)),false,name);
  assert.equal(/已到账|已入账/.test(body.textContent),credited,name);assert.equal(findAll(body,e=>hasClass(e,'native-pay-success')).length,credited?1:0,name);
  if(name==='paid-entitlement-pending'){assert.match(body.textContent,/权益处理中/);assert.equal(timers.size,1);assert.equal(buttons(body).some(e=>e.textContent==='刷新支付状态'),true);}
  results.push('native-render-'+name+' PASS');
 }
 {const {c,nodes}=make({renderDom:true}),v={...value(),attempted:true,order:{...base}};let reads=0;c.nativeRecoverOriginal=show=>{assert.equal(show,true);reads++;};c.nativeRenderOrder(v);
  const body=nodes.get('native-checkout-dialog').children[1];assert.match(body.textContent,/原付款二维码不在当前会话中/);assert.equal(findAll(body,e=>e.tagName==='CANVAS').length,0);assert.equal(buttons(body).some(e=>e.textContent==='生成支付二维码'),false);
  await find(body,e=>e.tagName==='BUTTON'&&e.textContent==='刷新支付状态').click();assert.equal(reads,1);results.push('native-missing-parameters-verifies-only PASS');
 }
 {const f=make({renderDom:true}),{c,nodes}=f,v={...value(),attempted:true,checkout:'weixin://wxpay/bizpayurl?pr=SyntheticOnly',order:{...base}};set(c,'_nativeCheckout',v);c.nativeRenderOrder(v);
  const original=nodes.get('native-checkout-dialog');assert.equal(findAll(original.children[1],e=>e.tagName==='CANVAS').length,1);let reads=0;c.fetch=async(url,opt)=>{reads++;assert.equal(url,'https://offline.invalid/payments/orders/'+base.id);assert.equal(opt.method,undefined);assert.equal(opt.headers['Idempotency-Key'],v.key);return json({...base,payment_status:'succeeded'});};
  await c.nativeRecoverOriginal(false);const dialog=nodes.get('native-checkout-dialog');assert.notEqual(dialog,original);assert.equal(find(dialog.children[1],e=>e.tagName==='H3').textContent,'支付已确认');assert.equal(findAll(dialog.children[1],e=>e.tagName==='CANVAS').length,0);assert.doesNotMatch(dialog.children[1].textContent,/已到账|已入账/);assert.equal(reads,1);assert.equal(f.billingReads,0);results.push('native-pending-to-paid-pending-removes-QR-without-credit PASS');
 }
 console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1);});
