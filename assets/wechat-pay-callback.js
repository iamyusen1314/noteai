/* This page exchanges one OAuth code for a checkout context, never a login or an order. */
(function () {
  'use strict';
  const query=new URLSearchParams(window.location.search),codes=query.getAll('code'),states=query.getAll('state');
  // Remove authorization parameters before any asynchronous work or navigation.
  window.history.replaceState(null,'','/wechat-pay.html');
  const status=document.getElementById('wechat-pay-status');
  const fail=message=>{status.textContent=message+'。尚未创建新订单，请返回原账户核实；不会自动重试授权或下单。';};
  async function complete() {
    try {
      if(codes.length!==1 || states.length!==1 || !/^[A-Za-z0-9_-]{1,256}$/.test(codes[0]) || !/^[A-Za-z0-9_-]{24,128}$/.test(states[0]))throw Error('微信授权返回参数无效或已取消');
      const token=localStorage.getItem('noteai_token');if(!token)throw Error('原 NoteAI 登录已失效');
      const current=()=>localStorage.getItem('noteai_token')===token;
      const headers={Authorization:'Bearer '+token};
      const me=await fetch('/auth/me',{headers,cache:'no-store',redirect:'error',credentials:'omit',referrerPolicy:'no-referrer'});
      const user=await me.json();if(!me.ok || typeof user.id!=='string' || !current())throw Error('原 NoteAI 账户尚未确认');
      const storageKey='noteai-native:'+user.id,raw=sessionStorage.getItem(storageKey),value=JSON.parse(raw||'null');
      if(!value || value.user_id!==user.id || value.method!=='jsapi' || value.attempted || value.oauth_state!==states[0] || typeof value.key!=='string' || !value.key || value.checkout_context)throw Error('原支付授权上下文已失效或已处理');
      // Mark before dispatch: browser reloads and duplicate redirects cannot exchange this code again.
      if(value.oauth_completion_attempted)throw Error('原微信授权结果需要核实');
      value.oauth_completion_attempted=true;sessionStorage.setItem(storageKey,JSON.stringify(value));
      const response=await fetch('/payments/wechat/oauth/complete',{method:'POST',headers:{...headers,'Content-Type':'application/json'},cache:'no-store',redirect:'error',credentials:'omit',referrerPolicy:'no-referrer',body:JSON.stringify({state:states[0],code:codes[0]})});
      const result=await response.json();
      if(!current() || JSON.parse(sessionStorage.getItem(storageKey)||'null')?.oauth_state!==states[0])throw Error('账户或原支付授权已切换');
      if(!response.ok || result.checkout_context!==states[0])throw Error('微信授权结果未确认');
      value.checkout_context=result.checkout_context;sessionStorage.setItem(storageKey,JSON.stringify(value));
      status.textContent='微信授权已确认，正在返回原账户；请点击继续支付后核对原商品与金额。';
      window.location.replace('/');
    }catch(error){fail(error.message||'微信授权暂不可用');}
  }
  void complete();
})();
