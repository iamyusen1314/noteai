/* Original order APIs only. Refresh/poll never submits a provider request. */
let _nativeCapability = null;
let _nativeCapabilityRead = 0;
let _nativeCheckout = null;
let _nativeBusy = false;
let _nativeTimer = null;
let _nativeReadBusy = false;
let _nativeViewGeneration = 0;
const NATIVE_UUID = /^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$/;
function nativePaymentEnvironment() {
  const ua=typeof navigator === 'undefined' ? '' : navigator.userAgent || '';
  if (/MicroMessenger/i.test(ua)) return 'wechat';
  return /Android|iPhone|iPad|iPod|Mobile/i.test(ua) ? 'mobile' : 'desktop';
}
function nativePaymentHint() {
  const env=nativePaymentEnvironment();
  return env==='desktop' ? '当前使用微信 Native 扫码支付，请用手机微信扫描本页面二维码；支付宝暂未开放。' :
    (env==='wechat' ? '微信内置浏览器' : '手机浏览器')+'当前只能展示 Native 支付二维码，不能在本机直接拉起支付。请在电脑或另一屏幕打开本站并登录同一账户，再用微信扫码；也可由另一台已登录付款微信的手机扫码。不保证长按识别可用，JSAPI 和 H5 支付尚未接入；H5 已申请，待审核通过后更新。';
}
function nativeMoney(fen) { return '¥' + (Number(fen) / 100).toFixed(2); }
function nativeOrderState(order) {
  if (order.refund_status === 'refunded' && order.refunded_fen === order.amount_fen)
    return {text:'已全额原路退款', terminal:true};
  if (order.refund_status === 'needs_manual')
    return {text:'退款结果需要核实，请联系客服；请勿重复付款', terminal:true};
  if (order.refund_status === 'pending')
    return {text:'退款处理中，以原订单核实结果为准', terminal:false};
  if (order.payment_status === 'needs_manual' || order.entitlement_status === 'needs_manual')
    return {text:'结果需要核实，请勿重复付款；请联系页面底部客服', terminal:true};
  if (order.payment_status === 'succeeded')
    return {text:order.entitlement_status === 'applied' ? '支付已确认，权益已入账' : '支付已确认，权益处理中',
      terminal:order.entitlement_status === 'applied'};
  if (['failed','closed'].includes(order.payment_status))
    return {text:order.payment_status === 'closed' ? '订单已关闭' : '支付未成功', terminal:true};
  return {text:'等待微信支付确认；请勿重复付款', terminal:false};
}
function nativeReadStorage() {
  if (!_authUser?.id) return null;
  const raw=sessionStorage.getItem('noteai-native:'+_authUser.id);
  if (!raw) return null;
  const value=JSON.parse(raw);
  if (value.user_id !== _authUser.id || typeof value.key !== 'string') throw Error('订单恢复记录无效，请联系客服');
  return value;
}
function nativeSaveStorage(value) {
  if (!value.key) return; // Read-only history must not replace an unresolved submission.
  sessionStorage.setItem('noteai-native:'+value.user_id,JSON.stringify(value));
}
async function refreshNativeCapabilities() {
  const token=_authToken, generation=++_nativeCapabilityRead;
  try {
    const response=await fetch(API_BASE+'/payments/capabilities',{headers:authHeader(),cache:'no-store'});
    if (!response.ok) throw Error('支付状态暂不可用');
    const value=await response.json();
    if (generation!==_nativeCapabilityRead || token!==_authToken) return;
    _nativeCapability=value;
  } catch (_) { if(generation===_nativeCapabilityRead) _nativeCapability=null; }
  nativeSyncControls();
}
function nativeAllowed(kind,id) {
  if (!_nativeCapability?.ordering_available || !_nativeCapability.providers?.includes('wechatpay_direct')) return false;
  const canary=_nativeCapability.canary_checkout;
  return !canary || (canary.product_kind===kind && canary.product_id===id);
}
function nativeSyncControls() {
  const notice=document.getElementById('public-pricing-notice');
  if(notice) notice.textContent='赠送与购买同等权益使用同一正式流程，开放情况见服务状态。'+
    (_nativeCapability?.canary_checkout ? '当前仅向已授权本人开放原价微信自测订单，公众收款尚未开放。' :
      _nativeCapability?.ordering_available ? '微信扫码支付已开放；支付宝暂未开放。' : '支付暂未开放，现有账户权益正常使用。');
  document.querySelectorAll('[data-product-action="handleUpgrade"],[data-product-action="handleTopup"]').forEach(el=>{
    let args=[];try{args=JSON.parse(el.dataset.productArgs||'[]');}catch(_){}
    const kind=el.dataset.productAction==='handleUpgrade'?'subscription':'credit_package';
    const open=nativeAllowed(kind,args[0]);
    el.setAttribute('aria-disabled',String(!open));el.title=open?nativePaymentHint():'此套餐当前未开放购买';
    if(el.tagName==='BUTTON'){el.disabled=!open;el.textContent=open?(nativePaymentEnvironment()==='desktop'?'微信扫码购买':'查看扫码购买方式'):'暂不可购买';}
  });
  const pricing=document.getElementById('pricing-content');
  if(pricing && !document.getElementById('native-payment-environment')) {
    const note=document.createElement('p');note.id='native-payment-environment';note.className='billing-preview';note.textContent=nativePaymentEnvironment()==='desktop' ? '微信 Native：用手机微信扫描电脑上的付款二维码。' : '当前为 Native 扫码支付，手机本机不能直接拉起付款；请另屏展示二维码后扫码。创建订单前可查看完整说明。';pricing.prepend(note);
  }
  if(pricing && !document.getElementById('native-order-history')) {
    const button=document.createElement('button');button.id='native-order-history';button.type='button';
    button.textContent='查看本人支付订单';button.addEventListener('click',nativeShowOrders);pricing.append(button);
  }
}
function nativeCloseCheckout() {
  clearTimeout(_nativeTimer);_nativeTimer=null;++_nativeViewGeneration;
  document.getElementById('native-checkout-dialog')?.remove();
}
function nativeClearSession() {
  nativeCloseCheckout();_nativeCapability=null;++_nativeCapabilityRead;_nativeCheckout=null;
  // Keep an uncertain original order identity bound to this account for later readback.
}
function nativeDialog(title,body) {
  nativeCloseCheckout();const dialog=document.createElement('dialog');dialog.id='native-checkout-dialog';
  dialog.style.cssText='box-sizing:border-box;margin:auto;max-width:520px;width:90vw;max-height:85dvh;overflow:auto;overflow-wrap:anywhere;border-radius:16px;padding:24px;background:var(--surf-1);color:var(--text);border:1px solid var(--border)';
  const heading=document.createElement('h2');heading.textContent=title;
  const close=document.createElement('button');close.className='btn btn-ghost';close.textContent='关闭';close.addEventListener('click',nativeCloseCheckout);
  body.querySelectorAll('button').forEach(button=>{button.className='btn btn-primary';button.type='button';});
  dialog.append(heading,body,close);document.body.append(dialog);dialog.addEventListener('cancel',nativeCloseCheckout);dialog.showModal();
  return dialog;
}
function nativeErrorText(value,fallback) {
  const detail=value?.detail;
  return typeof detail==='string' ? detail : fallback;
}
async function nativeStartCheckout(kind,id) {
  if(!_authToken){openAuthModal('login');return;}
  if(!requireProductConsent() || _nativeBusy)return;
  const owner=_authUser?.id,token=_authToken;
  await refreshNativeCapabilities();
  if(owner!==_authUser?.id || token!==_authToken)return;
  if(!nativeAllowed(kind,id)){showToast('此套餐当前未开放购买；现有权益仍可使用');return;}
  try {
    const response=await fetch(API_BASE+'/billing/tiers',{cache:'no-store'});if(!response.ok)throw Error('无法核对当前套餐金额');
    const catalog=await response.json();const product=kind==='subscription'?catalog.tiers?.[id]:(catalog.topup_packages||[]).find(p=>p.id===id);
    if(owner!==_authUser?.id || token!==_authToken)return;
    const fen=Math.round(Number(kind==='subscription'?product?.price:product?.price_rmb)*100);
    if(!product || !Number.isSafeInteger(fen) || fen<=0)throw Error('当前套餐金额无效');
    const canary=_nativeCapability.canary_checkout;if(canary && fen!==canary.amount_fen)throw Error('自测范围与正式套餐金额不一致');
    let original=nativeReadStorage();
    if(original && original.attempted){
      _nativeCheckout=original;const refreshed=await nativeRecoverOriginal(false);
      if(owner!==_authUser?.id || token!==_authToken)return;
      const old=original.order;
      const canaryFinished=old && ((['failed','closed'].includes(old.payment_status) && old.refund_status==='none') ||
        (old.refund_status==='refunded' && old.refunded_fen===old.amount_fen && old.entitlement_status==='reversed'));
      const newCanaryIdentity=typeof canary?.idempotency_key==='string' && canary.idempotency_key.length>0 && canary.idempotency_key!==original.key;
      const newPurchaseAllowed=refreshed && old && (original.canary ?
        canaryFinished && (!canary || newCanaryIdentity) : (['failed','closed'].includes(old.payment_status) ||
        (old.payment_status==='succeeded' && old.entitlement_status==='applied') ||
        (old.refund_status==='refunded' && old.refunded_fen===old.amount_fen)));
      if(!newPurchaseAllowed){if(old)nativeRenderOrder(original);else showToast('原订单待核实，请勿重复下单');return;}
    }
    const value={user_id:_authUser.id,product_kind:kind,product_id:id,amount_fen:fen,
      key:canary?.idempotency_key||('native-'+crypto.randomUUID()),canary:!!canary,attempted:false};
    const body=document.createElement('div');const text=document.createElement('p');
    text.textContent=(product.name||id)+' · '+nativeMoney(fen)+' · 微信支付'+(kind==='subscription'?'，一次性30天，不自动续费':'');body.append(text);
    const environment=document.createElement('p');environment.id='native-checkout-environment';environment.textContent=nativePaymentHint();body.append(environment);
    if(canary){const note=document.createElement('p');note.textContent=canary.notice;body.append(note);}
    const confirm=document.createElement('button');confirm.textContent='确认创建 '+nativeMoney(fen)+' 支付二维码';
    confirm.addEventListener('click',()=>nativeSubmitCheckout(value));body.append(confirm);nativeDialog('核对订单',body);
  }catch(e){showToast(e.message||'订单准备失败');}
}
async function nativeSubmitCheckout(value) {
  if(_nativeBusy || value.user_id!==_authUser?.id)return;
  const token=_authToken;_nativeBusy=true;_nativeCheckout=value;
  try {
    // The deterministic canary identity is also read before its first browser submission.
    const prior=await fetch(API_BASE+'/payments/orders',{headers:{...authHeader(),'Idempotency-Key':value.key},cache:'no-store'});
    const existing=await prior.json();if(!prior.ok)throw Error(nativeErrorText(existing,'无法确认原订单，尚未下单'));
    if(existing.orders?.length){value.attempted=true;value.order=existing.orders[0];nativeSaveStorage(value);nativeRenderOrder(value);return;}
    if(value.user_id!==_authUser?.id || token!==_authToken)return;
    if(value.attempted)throw Error('原提交结果尚未确认，请勿重复创建订单');
    if(typeof qrcode!=='function')throw Error('二维码组件未加载，尚未下单');
    value.attempted=true;nativeSaveStorage(value);
    const response=await fetch(API_BASE+'/payments/orders',{method:'POST',headers:{...authHeader(),'Content-Type':'application/json','Idempotency-Key':value.key},
      body:JSON.stringify({product_kind:value.product_kind,product_id:value.product_id,provider:'wechatpay_direct'})});
    const result=await response.json();
    if(!response.ok)throw Error(nativeErrorText(result,'提交结果需要核实'));
    if(!NATIVE_UUID.test(result.order?.id) || result.order.amount_fen!==value.amount_fen || result.order.provider_mode!=='live')throw Error('订单身份或金额不一致，请勿付款');
    value.order=result.order;
    const checkout=JSON.parse(result.checkout);
    if(checkout.channel!=='wechatpay_native' || checkout.kind!=='qr_text' || typeof checkout.value!=='string' ||
       !/^weixin:\/\/wxpay\/bizpayurl\?[A-Za-z0-9_%=&.-]+$/.test(checkout.value) || checkout.value.length>2048)throw Error('支付二维码未确认，请勿重复提交');
    value.checkout=checkout.value;nativeSaveStorage(value);
    if(value.user_id===_authUser?.id)nativeRenderOrder(value);
  }catch(e){
    if(value.user_id===_authUser?.id){
      const body=document.createElement('div');const text=document.createElement('p');
      text.textContent=(e.message||'网络中断')+'。只核实原订单，不自动重新下单。';body.append(text);
      const read=document.createElement('button');read.textContent='核实原订单';read.addEventListener('click',()=>nativeRecoverOriginal(true));body.append(read);nativeDialog('订单结果待核实',body);
      if(value.attempted)await nativeRecoverOriginal(false);
    }
  }finally{_nativeBusy=false;}
}
function nativeRenderOrder(value) {
  if(value.user_id!==_authUser?.id || !NATIVE_UUID.test(value.order?.id))return;
  const body=document.createElement('div');const order=value.order,state=nativeOrderState(order);
  const info=document.createElement('p');info.textContent=nativeMoney(order.amount_fen)+' · '+order.product_id+' · 订单 '+order.id;
  const status=document.createElement('p');status.id='native-order-state';status.textContent=state.text;body.append(info,status);
  if(value.checkout && !state.terminal && order.payment_status!=='succeeded'){
    const qr=qrcode(0,'M');qr.addData(value.checkout,'Byte');qr.make();const count=qr.getModuleCount(),cell=6;
    const canvas=document.createElement('canvas');canvas.width=canvas.height=(count+8)*cell;canvas.style.cssText='max-width:100%;height:auto';canvas.setAttribute('aria-label','微信支付二维码，金额'+nativeMoney(order.amount_fen));
    const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.fillStyle='#000';
    for(let y=0;y<count;y++)for(let x=0;x<count;x++)if(qr.isDark(y,x))context.fillRect((x+4)*cell,(y+4)*cell,cell,cell);
    body.append(canvas);const tip=document.createElement('p');tip.textContent=nativePaymentHint()+' 请在付款微信上再次核对商户和金额。';body.append(tip);
  }else if(!state.terminal && order.payment_status!=='succeeded'){
    const note=document.createElement('p');note.textContent='原二维码不在当前会话中；请勿重复下单，联系客服核实原订单。';body.append(note);
  }
  if(order.payment_status==='succeeded' && order.entitlement_status==='applied' && typeof returnFromPricing==='function') {
    const back=document.createElement('button');back.textContent='权益已到账，返回原任务';back.addEventListener('click',()=>{nativeCloseCheckout();returnFromPricing();});body.append(back);
  }
  const read=document.createElement('button');read.textContent='刷新原订单状态';read.addEventListener('click',()=>nativeRecoverOriginal(true));body.append(read);
  nativeDialog(value.canary?'本人授权的微信支付自测':'微信支付订单',body);
  if(!state.terminal){const generation=_nativeViewGeneration;let remaining=60;
    const poll=async()=>{if(generation!==_nativeViewGeneration || value.user_id!==_authUser?.id || remaining--<=0)return;
      await nativeRecoverOriginal(false);if(generation===_nativeViewGeneration && !nativeOrderState(value.order).terminal)_nativeTimer=setTimeout(poll,5000);};
    _nativeTimer=setTimeout(poll,5000);
  }
}
async function nativeRecoverOriginal(show) {
  const value=_nativeCheckout;if(!value || value.user_id!==_authUser?.id || _nativeReadBusy)return;
  const generation=_nativeViewGeneration;_nativeReadBusy=true;
  try{
    const path=value.order?.id?'/payments/orders/'+value.order.id:'/payments/orders';
    const r=await fetch(API_BASE+path,{headers:{...authHeader(),'Idempotency-Key':value.key},cache:'no-store'});const data=await r.json();
    if(!r.ok)throw Error(nativeErrorText(data,'无法读取原订单'));
    const order=value.order?.id?data:data.orders?.[0];
    if(!order){if(show)showToast('尚未查到原订单；不自动重发，请稍后核实');return;}
    if(!NATIVE_UUID.test(order.id) || order.amount_fen!==value.amount_fen)throw Error('原订单身份不一致');
    value.order=order;nativeSaveStorage(value);if(value.user_id!==_authUser?.id || generation!==_nativeViewGeneration)return;
    const state=nativeOrderState(order);const el=document.getElementById('native-order-state');if(el)el.textContent=state.text;
    if(show || state.terminal){nativeRenderOrder(value);if(state.terminal)loadBillingPlan();}
    return true;
  }catch(e){if(show && value.user_id===_authUser?.id)showToast(e.message||'订单读取失败');}
  finally{_nativeReadBusy=false;}
}
async function nativeShowOrders() {
  if(!_authToken){openAuthModal('login');return;}const owner=_authUser?.id;
  try{
    const r=await fetch(API_BASE+'/payments/orders',{headers:authHeader(),cache:'no-store'});const data=await r.json();
    if(!r.ok)throw Error(nativeErrorText(data,'订单读取失败'));if(owner!==_authUser?.id)return;
    const body=document.createElement('div');
    if(!data.orders?.length){const p=document.createElement('p');p.textContent='暂无本人支付订单';body.append(p);}
    for(const order of data.orders||[]){const button=document.createElement('button');button.style.cssText='display:block;margin:12px 0;max-width:100%;overflow-wrap:anywhere';
      button.textContent=order.created_at.slice(0,10)+' · '+nativeMoney(order.amount_fen)+' · '+nativeOrderState(order).text;
      button.addEventListener('click',()=>{let saved=null;try{saved=nativeReadStorage();}catch(_){}
        _nativeCheckout=saved?.order?.id===order.id?saved:{user_id:owner,order,amount_fen:order.amount_fen,key:'',attempted:true};nativeRenderOrder(_nativeCheckout);});body.append(button);}
    nativeDialog('本人支付订单',body);
  }catch(e){showToast(e.message||'订单读取失败');}
}
