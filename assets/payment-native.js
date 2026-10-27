/* Original order APIs only. Refresh/poll never submits a provider request. */
let _nativeCapability = null;
let _nativeCapabilityRead = 0;
let _nativeCheckout = null;
let _nativeBusy = false;
let _nativeTimer = null;
let _nativeReadBusy = false;
let _nativeViewGeneration = 0;
let _nativeResumeOffered = '';
let _nativeBridgeBusy = false;
let _nativeRefreshBusy = false;
const NATIVE_UUID = /^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$/;
const WECHAT_CHECKOUT_CONTEXT = /^[A-Za-z0-9_-]{24,128}$/;
function nativePaymentEnvironment() {
  const ua=typeof navigator === 'undefined' ? '' : navigator.userAgent || '';
  if (/MicroMessenger/i.test(ua)) return 'wechat';
  return /Android|iPhone|iPad|iPod|Mobile/i.test(ua) ? 'mobile' : 'desktop';
}
function nativeJsapiAvailable() {
  return nativePaymentEnvironment()==='wechat' && _nativeCapability?.wechat_jsapi_available===true;
}
function nativePaymentHint(nativeOrder=false) {
  const env=nativePaymentEnvironment();
  if(!nativeOrder && nativeJsapiAvailable())return '在当前微信内完成授权后可直接唤起微信支付，无需另外扫码；付款后以原订单确认结果为准。';
  if(_nativeCapability?.wechat_jsapi_available===true && env!=='desktop')return '此订单使用 Native 扫码支付，请在另一屏幕展示二维码后用微信扫码。新的购买可在微信内打开本站并登录同一账户，使用本机微信支付。';
  return env==='desktop' ? '当前使用微信 Native 扫码支付，请用手机微信扫描本页面二维码；支付宝暂未开放。' :
    (env==='wechat' ? '微信内置浏览器' : '手机浏览器')+'当前只能展示 Native 支付二维码，不能在本机直接拉起支付。请在电脑或另一屏幕打开本站并登录同一账户，再用微信扫码；也可由另一台已登录付款微信的手机扫码。不保证长按识别可用；当前查询未确认微信内直接支付可用，H5 支付当前未开放。';
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
  if(notice) notice.textContent='赠送与购买同等权益使用同一正式流程。'+
    (typeof productPaymentDisclosureText==='function' ? productPaymentDisclosureText(_nativeCapability) : '付款状态暂无法确认，请以结算页当前查询结果为准。');
  document.querySelectorAll('[data-product-action="handleUpgrade"],[data-product-action="handleTopup"]').forEach(el=>{
    let args=[];try{args=JSON.parse(el.dataset.productArgs||'[]');}catch(_){}
    const kind=el.dataset.productAction==='handleUpgrade'?'subscription':'credit_package';
    const open=nativeAllowed(kind,args[0]);
    el.setAttribute('aria-disabled',String(!open));el.title=open?nativePaymentHint():'此套餐当前未开放购买';
    if(el.tagName==='BUTTON'){el.disabled=!open;el.textContent=open?(nativeJsapiAvailable()?'微信内直接购买':nativePaymentEnvironment()==='desktop'?'微信扫码购买':'查看扫码购买方式'):'暂不可购买';}
  });
  const pricing=document.getElementById('pricing-content');
  if(pricing && !document.getElementById('native-payment-environment')) {
    const note=document.createElement('p');note.id='native-payment-environment';note.className='billing-preview';pricing.prepend(note);
  }
  const environment=document.getElementById('native-payment-environment');if(environment)environment.textContent=nativePaymentHint();
  if(pricing && !document.getElementById('native-order-history')) {
    const button=document.createElement('button');button.id='native-order-history';button.type='button';
    button.textContent='查看本人支付订单';button.addEventListener('click',nativeShowOrders);pricing.append(button);
  }
  if(typeof renderProductFacts==='function')renderProductFacts();
  nativeOfferWechatResume();
}
function nativeCloseCheckout() {
  clearTimeout(_nativeTimer);_nativeTimer=null;++_nativeViewGeneration;
  document.getElementById('native-checkout-dialog')?.remove();
}
function nativeClearSession() {
  nativeCloseCheckout();_nativeCapability=null;++_nativeCapabilityRead;_nativeCheckout=null;_nativeResumeOffered='';
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
    if(original?.method==='jsapi' && original.attempted && original.jsapi_precreate_rejection && !original.order){nativeShowWechatContextRecovery(original);return;}
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
    if(original?.method==='jsapi' && !original.attempted && original.checkout_context){nativeShowWechatResume(original);return;}
    if(original?.method==='jsapi' && !original.attempted && (original.oauth_state || original.oauth_restart_required)){nativeShowWechatRestart(original);return;}
    const value={user_id:_authUser.id,product_kind:kind,product_id:id,amount_fen:fen,
      key:canary?.idempotency_key||('native-'+crypto.randomUUID()),canary:!!canary,attempted:false,
      method:nativeJsapiAvailable()?'jsapi':'native'};
    const body=document.createElement('div');const text=document.createElement('p');
    text.textContent=(product.name||id)+' · '+nativeMoney(fen)+' · 微信支付'+(kind==='subscription'?'，一次性30天，不自动续费':'');body.append(text);
    const environment=document.createElement('p');environment.id='native-checkout-environment';environment.textContent=nativePaymentHint();body.append(environment);
    if(canary){const note=document.createElement('p');note.textContent=canary.notice;body.append(note);}
    const confirm=document.createElement('button');confirm.textContent=value.method==='jsapi'?'授权并继续微信支付':'确认创建 '+nativeMoney(fen)+' 支付二维码';
    confirm.addEventListener('click',()=>value.method==='jsapi'?nativeBeginWechatCheckout(value):nativeSubmitCheckout(value));body.append(confirm);nativeDialog('核对订单',body);
  }catch(e){showToast(e.message||'订单准备失败');}
}
function nativeOfferWechatResume() {
  if(typeof _authUser==='undefined' || !_authUser?.id || typeof _authToken==='undefined' || !_authToken || !nativeJsapiAvailable() || _nativeBusy)return;
  try {const value=nativeReadStorage();
    if(value?.method!=='jsapi' || (value.attempted && (!value.jsapi_precreate_rejection || value.order)) || (!WECHAT_CHECKOUT_CONTEXT.test(value.checkout_context||'') && !value.oauth_state && !value.oauth_restart_required && !value.jsapi_precreate_rejection))return;
    const identity=value.user_id+':'+value.key;if(identity===_nativeResumeOffered)return;
    _nativeResumeOffered=identity;
    if(value.attempted)nativeShowWechatContextRecovery(value);
    else if(WECHAT_CHECKOUT_CONTEXT.test(value.checkout_context||''))nativeShowWechatResume(value);else nativeShowWechatRestart(value);
  }catch(_){/* Invalid browser records never dispatch an order. */}
}
function nativeShowWechatResume(value) {
  if(value.user_id!==_authUser?.id || !nativeJsapiAvailable())return;
  const body=document.createElement('div'),text=document.createElement('p'),button=document.createElement('button');
  text.textContent='微信授权已完成。继续原商品 '+value.product_id+' · '+nativeMoney(value.amount_fen)+'，确认后仅创建这一笔订单；不会自动付款。';
  button.textContent='继续本人微信支付';button.addEventListener('click',()=>nativeSubmitCheckout(value));body.append(text,button);nativeDialog('继续微信支付',body);
}
function nativeShowWechatRestart(value,message='微信授权未完成或已过期。') {
  if(value.user_id!==_authUser?.id || value.attempted || !nativeJsapiAvailable())return;
  const body=document.createElement('div'),text=document.createElement('p'),button=document.createElement('button');
  text.textContent=message+' 请先核实订单状态，再重新授权继续付款。';
  button.textContent='重新微信授权';button.addEventListener('click',()=>nativeRestartWechatCheckout(value));body.append(text,button);nativeDialog('重新微信授权',body);
}
function nativeShowWechatContextRecovery(value) {
  if(value.user_id!==_authUser?.id || value.order || !['WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED','WECHAT_JSAPI_CONTEXT_INVALID'].includes(value.jsapi_precreate_rejection))return;
  const body=document.createElement('div'),text=document.createElement('p'),button=document.createElement('button');
  text.textContent='微信授权已过期或未完成。请先核实订单状态，再重新授权继续付款；不会自动重新下单。';
  button.textContent='核实原订单以重新授权';button.addEventListener('click',async()=>{try{if(await nativeVerifyWechatRestart(value))nativeShowWechatRestart(value);}catch(e){showToast(e.message||'无法核实原订单');}});
  body.append(text,button);nativeDialog('核实原微信支付授权',body);
}
function nativeResetWechatAuthorization(value) {
  for(const name of ['checkout_context','oauth_state','oauth_completion_attempted','jsapi_params','jsapi_precreate_rejection'])delete value[name];
  value.attempted=false;value.oauth_restart_required=true;nativeSaveStorage(value);
}
async function nativeVerifyWechatRestart(value) {
  const token=_authToken,generation=_nativeViewGeneration;
  if(value.user_id!==_authUser?.id || value.method!=='jsapi' || value.order ||
    (value.attempted && !['WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED','WECHAT_JSAPI_CONTEXT_INVALID'].includes(value.jsapi_precreate_rejection)))return false;
  const response=await fetch(API_BASE+'/payments/orders',{headers:{...authHeader(),'Idempotency-Key':value.key},cache:'no-store'}),result=await response.json();
  if(value.user_id!==_authUser?.id || token!==_authToken || generation!==_nativeViewGeneration)return false;
  if(!response.ok || !Array.isArray(result.orders))throw Error('暂时无法确认订单状态，请稍后核实后再重新授权');
  if(result.orders.length){
    const order=result.orders[0];if(!NATIVE_UUID.test(order?.id) || order.amount_fen!==value.amount_fen)throw Error('原订单身份或金额不一致');
    value.order=order;value.attempted=true;nativeSaveStorage(value);_nativeCheckout=value;nativeRenderOrder(value);return false;
  }
  nativeResetWechatAuthorization(value);return true;
}
async function nativeRestartWechatCheckout(value) {
  if(_nativeBusy || value.user_id!==_authUser?.id || value.attempted || !nativeJsapiAvailable())return;
  const token=_authToken;_nativeBusy=true;let allowed=false;
  try{allowed=await nativeVerifyWechatRestart(value);}catch(e){if(value.user_id===_authUser?.id && token===_authToken)showToast(e.message||'无法核实原订单');}
  finally{_nativeBusy=false;}
  if(allowed && value.user_id===_authUser?.id && token===_authToken)await nativeBeginWechatCheckout(value);
}
async function nativeBeginWechatCheckout(value) {
  if(_nativeBusy || value.user_id!==_authUser?.id || value.attempted || !nativeJsapiAvailable())return;
  const token=_authToken,generation=_nativeViewGeneration;_nativeBusy=true;
  try {
    value.oauth_restart_required=true;nativeSaveStorage(value);
    const response=await fetch(API_BASE+'/payments/wechat/oauth/begin',{method:'POST',headers:{...authHeader(),'Content-Type':'application/json','Idempotency-Key':value.key},
      cache:'no-store',redirect:'error',body:JSON.stringify({product_kind:value.product_kind,product_id:value.product_id})});
    const result=await response.json();if(value.user_id!==_authUser?.id || token!==_authToken || generation!==_nativeViewGeneration)return;
    if(!response.ok)throw Error('微信授权暂不可用，请稍后重新授权');
    const url=new URL(result.authorize_url),callback=new URL(url.searchParams.get('redirect_uri'));
    const state=url.searchParams.get('state');
    if(url.origin!=='https://open.weixin.qq.com' || url.pathname!=='/connect/oauth2/authorize' || url.username || url.password ||
       url.searchParams.get('response_type')!=='code' || url.searchParams.get('scope')!=='snsapi_base' ||
       !/^wx[0-9a-f]{16}$/.test(url.searchParams.get('appid')||'') || !WECHAT_CHECKOUT_CONTEXT.test(state||'') ||
       (result.state && result.state!==state) || callback.origin!==window.location.origin || callback.pathname!=='/wechat-pay.html' || callback.search || callback.hash)
      throw Error('微信授权地址未确认，尚未创建订单');
    value.oauth_state=state;value.method='jsapi';value.oauth_restart_required=false;nativeSaveStorage(value);
    window.location.assign(url.href);
  }catch(e){if(value.user_id===_authUser?.id && token===_authToken && generation===_nativeViewGeneration)nativeShowWechatRestart(value,'微信授权暂不可用或未完成。');}
  finally{_nativeBusy=false;}
}
function nativeJsapiParams(params) {
  if(!params || typeof params!=='object' || !/^wx[0-9a-f]{16}$/.test(params.appId||'') ||
     !/^[1-9][0-9]{8,11}$/.test(params.timeStamp||'') || !/^[A-Za-z0-9_-]{16,128}$/.test(params.nonceStr||'') ||
     !/^prepay_id=[A-Za-z0-9_-]{1,256}$/.test(params.package||'') || params.signType!=='RSA' ||
     !/^[A-Za-z0-9+/]{128,1024}={0,2}$/.test(params.paySign||''))throw Error('微信支付参数未确认，请核实原订单');
  return {appId:params.appId,timeStamp:params.timeStamp,nonceStr:params.nonceStr,package:params.package,signType:'RSA',paySign:params.paySign};
}
function nativeWechatBridge() {
  return new Promise((resolve,reject)=>{
    if(typeof window!=='undefined' && typeof window.WeixinJSBridge?.invoke==='function'){resolve(window.WeixinJSBridge);return;}
    const ready=()=>{if(typeof window.WeixinJSBridge?.invoke==='function'){clearTimeout(timer);document.removeEventListener('WeixinJSBridgeReady',ready);resolve(window.WeixinJSBridge);}};
    const timer=setTimeout(()=>{document.removeEventListener('WeixinJSBridgeReady',ready);reject(Error('微信支付组件尚未就绪，请留在微信内稍后重试此原订单'));},5000);
    document.addEventListener('WeixinJSBridgeReady',ready);
  });
}
function nativeIsJsapiOrder(value) {
  return value?.order?.payment_method ? value.order.payment_method==='jsapi' : value?.method==='jsapi';
}
async function nativeRefreshWechatOrder(value,closeUnpaid=false) {
  if(_nativeRefreshBusy || !_authToken || value.user_id!==_authUser?.id || !nativeIsJsapiOrder(value) ||
    value.order?.provider_mode!=='live' || !NATIVE_UUID.test(value.order?.id))return;
  const token=_authToken,generation=_nativeViewGeneration,orderId=value.order.id;
  const current=()=>value.user_id===_authUser?.id && token===_authToken && generation===_nativeViewGeneration;
  const buttons=[...document.querySelectorAll('[data-wechat-order-refresh]')];
  const status=message=>{const el=document.getElementById('native-wechat-refresh-result');if(el)el.textContent=message;else showToast(message);};
  _nativeRefreshBusy=true;buttons.forEach(button=>{button.disabled=true;});
  try {
    const response=await fetch(API_BASE+'/payments/orders/'+orderId+'/refresh',{method:'POST',headers:{...authHeader(),'Content-Type':'application/json'},
      cache:'no-store',redirect:'error',body:JSON.stringify({close_unpaid:closeUnpaid===true})});
    const result=await response.json();if(!current())return;
    if(!response.ok){
      let message='微信支付结果尚未确认，请稍后核实原订单；请勿重新下单或重复付款。';
      if(response.status===429){
        const retryAfter=response.headers?.get('Retry-After'),seconds=typeof retryAfter==='string' && /^[1-9][0-9]{0,2}$/.test(retryAfter)?Number(retryAfter):0;
        message=seconds>=1 && seconds<=300?(closeUnpaid?'请在约'+seconds+'秒后再结束未付款订单；本次尚未结束订单。':'请在约'+seconds+'秒后再核实支付状态。')+'结果未确认时请勿重复付款。':'请稍后再核实微信支付状态；结果未确认时请勿重复付款。';
      }
      status(message);return;
    }
    const order=result.order;
    if(order?.id!==orderId || order.amount_fen!==value.amount_fen || order.provider_mode!=='live' || order.payment_method!=='jsapi'){
      status('原订单信息尚未确认，请联系客服核实；请勿重新下单或重复付款。');return;
    }
    const changed=['payment_status','entitlement_status','refund_status','refunded_fen'].some(name=>value.order[name]!==order[name]);
    value.order=order;value.method='jsapi';nativeSaveStorage(value);_nativeCheckout=value;
    if(changed || nativeOrderState(order).terminal)nativeRenderOrder(value);
    else status(closeUnpaid?'订单尚未确认结束，请稍后核实原订单；请勿重新下单或重复付款。':'微信尚未确认这笔付款，请稍后核实原订单；请勿重复付款。');
    if(nativeOrderState(order).terminal)loadBillingPlan();
  }catch(_){if(current())status('微信支付结果尚未确认，请稍后核实原订单；请勿重新下单或重复付款。');}
  finally{_nativeRefreshBusy=false;if(current())buttons.forEach(button=>{button.disabled=false;});}
}
async function nativeInvokeJsapi(value,button,status) {
  if(_nativeBridgeBusy || value.user_id!==_authUser?.id || nativePaymentEnvironment()!=='wechat')return;
  const token=_authToken,generation=_nativeViewGeneration;const current=()=>value.user_id===_authUser?.id && token===_authToken && generation===_nativeViewGeneration;
  _nativeBridgeBusy=true;button.disabled=true;
  try {
    const params=nativeJsapiParams(value.jsapi_params),bridge=await nativeWechatBridge();if(!current())return;
    await new Promise(resolve=>{
      let finished=false;const finish=message=>{if(finished)return;finished=true;clearTimeout(timer);
        if(current()){status.textContent=message;void nativeRefreshWechatOrder(value,false);}resolve();};
      const timer=setTimeout(()=>finish('付款窗口结果尚未确认，请核实原订单；请勿重新下单。'),60000);
      try {bridge.invoke('getBrandWCPayRequest',params,result=>{
          const outcome=result?.err_msg;
          finish(outcome==='get_brand_wcpay_request:cancel'?'已取消本次付款，原订单仍待确认；可继续支付同一订单。':
            outcome==='get_brand_wcpay_request:ok'?'微信已返回付款结果，正在核实原订单与权益到账；请勿重复付款。':'微信未确认付款结果，请核实原订单；请勿重新下单。');
        });
      }catch(_){finish('微信支付组件未确认付款，请核实原订单；请勿重新下单。');}
    });
  }catch(e){if(current())status.textContent=e.message||'微信支付未唤起，请核实原订单';}
  finally{_nativeBridgeBusy=false;if(current())button.disabled=false;}
}
async function nativeSubmitCheckout(value) {
  if(_nativeBusy || value.user_id!==_authUser?.id)return;
  const token=_authToken,generation=_nativeViewGeneration;_nativeBusy=true;_nativeCheckout=value;
  try {
    // The deterministic canary identity is also read before its first browser submission.
    const prior=await fetch(API_BASE+'/payments/orders',{headers:{...authHeader(),'Idempotency-Key':value.key},cache:'no-store'});
    const existing=await prior.json();if(value.user_id!==_authUser?.id || token!==_authToken || generation!==_nativeViewGeneration)return;
    if(!prior.ok)throw Error(nativeErrorText(existing,'无法确认原订单，尚未下单'));
    if(existing.orders?.length){value.attempted=true;value.order=existing.orders[0];nativeSaveStorage(value);nativeRenderOrder(value);return;}
    if(value.user_id!==_authUser?.id || token!==_authToken)return;
    if(value.attempted)throw Error('原提交结果尚未确认，请勿重复创建订单');
    const jsapi=value.method==='jsapi';
    if(jsapi && (!nativeJsapiAvailable() || !WECHAT_CHECKOUT_CONTEXT.test(value.checkout_context||'')))throw Error('微信授权尚未确认，尚未下单');
    if(!jsapi && typeof qrcode!=='function')throw Error('二维码组件未加载，尚未下单');
    value.attempted=true;nativeSaveStorage(value);
    const response=await fetch(API_BASE+'/payments/orders',{method:'POST',headers:{...authHeader(),'Content-Type':'application/json','Idempotency-Key':value.key},
      body:JSON.stringify({product_kind:value.product_kind,product_id:value.product_id,provider:'wechatpay_direct',...(jsapi?{wechat_jsapi_context:value.checkout_context}:{})})});
    const result=await response.json();
    if(!response.ok && jsapi && response.status===400 && ['WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED','WECHAT_JSAPI_CONTEXT_INVALID'].includes(result.detail)){
      value.jsapi_precreate_rejection=result.detail;nativeSaveStorage(value);
      if(await nativeVerifyWechatRestart(value)){nativeShowWechatRestart(value,'尚未创建付款订单，微信授权已过期或未完成。');return;}
    }
    if(!response.ok)throw Error(jsapi?'微信支付尚未完成，请先核实订单状态':nativeErrorText(result,'提交结果需要核实'));
    if(!NATIVE_UUID.test(result.order?.id) || result.order.amount_fen!==value.amount_fen || result.order.provider_mode!=='live')throw Error('订单身份或金额不一致，请勿付款');
    value.order=result.order;
    const checkout=JSON.parse(result.checkout);
    if(jsapi){
      if(checkout.channel!=='wechatpay_jsapi' || checkout.kind!=='bridge')throw Error('微信支付参数未确认，请核实原订单');
      value.jsapi_params=nativeJsapiParams(checkout.params);
    }else{
      if(checkout.channel!=='wechatpay_native' || checkout.kind!=='qr_text' || typeof checkout.value!=='string' ||
         !/^weixin:\/\/wxpay\/bizpayurl\?[A-Za-z0-9_%=&.-]+$/.test(checkout.value) || checkout.value.length>2048)throw Error('支付二维码未确认，请勿重复提交');
      value.checkout=checkout.value;
    }
    nativeSaveStorage(value);
    if(value.user_id===_authUser?.id && token===_authToken && generation===_nativeViewGeneration)nativeRenderOrder(value);
  }catch(e){
    if(value.user_id===_authUser?.id && token===_authToken && generation===_nativeViewGeneration){
      const body=document.createElement('div');const text=document.createElement('p');
      text.textContent=(e.message||'网络中断')+'。只核实原订单，不自动重新下单。';body.append(text);
      const read=document.createElement('button');read.textContent='核实原订单';read.addEventListener('click',async()=>{
        if(value.jsapi_precreate_rejection){try{if(await nativeVerifyWechatRestart(value))nativeShowWechatRestart(value);}catch(error){showToast(error.message||'无法核实原订单');}}
        else await nativeRecoverOriginal(true);
      });body.append(read);nativeDialog('订单结果待核实',body);
      if(value.attempted)await nativeRecoverOriginal(false);
    }
  }finally{_nativeBusy=false;}
}
function nativeRenderOrder(value) {
  if(value.user_id!==_authUser?.id || !NATIVE_UUID.test(value.order?.id))return;
  const body=document.createElement('div');const order=value.order,state=nativeOrderState(order);
  const info=document.createElement('p');info.textContent=nativeMoney(order.amount_fen)+' · '+order.product_id+' · 订单 '+order.id;
  const status=document.createElement('p');status.id='native-order-state';status.textContent=state.text;body.append(info,status);
  if(nativeIsJsapiOrder(value) && value.jsapi_params && !state.terminal && order.payment_status!=='succeeded'){
    const button=document.createElement('button'),note=document.createElement('p');button.textContent='在微信内支付此订单';
    button.disabled=nativePaymentEnvironment()!=='wechat';note.textContent=button.disabled?'请在原微信会话打开本站核实此订单；请勿重新下单。':'点击后在微信付款窗口核对商户和金额；取消付款不会新建订单。';
    button.addEventListener('click',()=>nativeInvokeJsapi(value,button,note));body.append(button,note);
  }else if(value.checkout && !state.terminal && order.payment_status!=='succeeded'){
    const qr=qrcode(0,'M');qr.addData(value.checkout,'Byte');qr.make();const count=qr.getModuleCount(),cell=6;
    const canvas=document.createElement('canvas');canvas.width=canvas.height=(count+8)*cell;canvas.style.cssText='max-width:100%;height:auto';canvas.setAttribute('aria-label','微信支付二维码，金额'+nativeMoney(order.amount_fen));
    const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.fillStyle='#000';
    for(let y=0;y<count;y++)for(let x=0;x<count;x++)if(qr.isDark(y,x))context.fillRect((x+4)*cell,(y+4)*cell,cell,cell);
    body.append(canvas);const tip=document.createElement('p');tip.textContent=nativePaymentHint(true)+' 请在付款微信上再次核对商户和金额。';body.append(tip);
  }else if(!state.terminal && order.payment_status!=='succeeded'){
    const note=document.createElement('p');note.textContent=nativeIsJsapiOrder(value)?'原付款参数不在当前会话中，请先核实微信支付状态。未付款时可结束原订单；结果未确认时请勿重新下单或重复付款。':'原付款二维码或微信支付参数不在当前会话中；请勿重复下单，联系客服核实原订单。';body.append(note);
  }
  if(order.payment_status==='succeeded' && order.entitlement_status==='applied' && typeof returnFromPricing==='function') {
    const back=document.createElement('button');back.textContent='权益已到账，返回原任务';back.addEventListener('click',()=>{nativeCloseCheckout();returnFromPricing();});body.append(back);
  }
  const read=document.createElement('button');read.textContent='刷新原订单状态';read.addEventListener('click',()=>nativeRecoverOriginal(true));body.append(read);
  if(nativeIsJsapiOrder(value) && order.provider_mode==='live' && !state.terminal){
    const note=document.createElement('p');note.id='native-wechat-refresh-result';note.textContent='先核实微信支付状态；已付款的订单不会关闭。结果未确认时，请勿重复付款。';body.append(note);
    const refresh=document.createElement('button');refresh.textContent='核实微信支付状态';refresh.setAttribute('data-wechat-order-refresh','');refresh.addEventListener('click',()=>nativeRefreshWechatOrder(value,false));body.append(refresh);
    if(order.payment_status!=='succeeded'){
      const close=document.createElement('button');close.textContent='结束未付款订单';close.setAttribute('data-wechat-order-refresh','');close.addEventListener('click',()=>nativeRefreshWechatOrder(value,true));body.append(close);
    }
  }
  nativeDialog(value.canary?'本人授权的微信支付自测':'微信支付订单',body);
  if(!state.terminal){const generation=_nativeViewGeneration;let remaining=60;
    const poll=async()=>{if(generation!==_nativeViewGeneration || value.user_id!==_authUser?.id || remaining--<=0)return;
      await nativeRecoverOriginal(false);if(generation===_nativeViewGeneration && !nativeOrderState(value.order).terminal)_nativeTimer=setTimeout(poll,5000);};
    _nativeTimer=setTimeout(poll,5000);
  }
}
async function nativeRecoverOriginal(show) {
  const value=_nativeCheckout;if(!value || value.user_id!==_authUser?.id || _nativeReadBusy)return;
  const token=_authToken,generation=_nativeViewGeneration;_nativeReadBusy=true;
  try{
    const path=value.order?.id?'/payments/orders/'+value.order.id:'/payments/orders';
    const r=await fetch(API_BASE+path,{headers:{...authHeader(),'Idempotency-Key':value.key},cache:'no-store'});const data=await r.json();
    if(value.user_id!==_authUser?.id || token!==_authToken || generation!==_nativeViewGeneration)return;
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
  if(!_authToken){openAuthModal('login');return;}const owner=_authUser?.id,token=_authToken;
  try{
    const r=await fetch(API_BASE+'/payments/orders',{headers:authHeader(),cache:'no-store'});const data=await r.json();
    if(!r.ok)throw Error(nativeErrorText(data,'订单读取失败'));if(owner!==_authUser?.id || token!==_authToken)return;
    const body=document.createElement('div');
    if(!data.orders?.length){const p=document.createElement('p');p.textContent='暂无本人支付订单';body.append(p);}
    for(const order of data.orders||[]){const button=document.createElement('button');button.style.cssText='display:block;margin:12px 0;max-width:100%;overflow-wrap:anywhere';
      button.textContent=order.created_at.slice(0,10)+' · '+nativeMoney(order.amount_fen)+' · '+nativeOrderState(order).text;
      button.addEventListener('click',()=>{let saved=null;try{saved=nativeReadStorage();}catch(_){}
        _nativeCheckout=saved?.order?.id===order.id?saved:{user_id:owner,order,amount_fen:order.amount_fen,key:'',attempted:true};nativeRenderOrder(_nativeCheckout);});body.append(button);}
    nativeDialog('本人支付订单',body);
  }catch(e){showToast(e.message||'订单读取失败');}
}
