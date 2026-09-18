const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Default is actual delivered HTML after this file is moved into tests/.
// Draft-only verification may explicitly select an external candidate; report it as such.
const sourcePath = process.env.NOTEAI_HTML_PATH || path.join(__dirname,'..','NoteAI_Pro_Demo_Framer.html');
const html = fs.readFileSync(sourcePath,'utf8');
function extract(name) {
  const match = new RegExp('^(?:async )?function '+name+'\\(','m').exec(html);
  assert.ok(match,'Missing actual source function '+name);
  return html.slice(match.index,html.indexOf('\n}',match.index)+2);
}
const functions = ['accountActionStart','accountActionJSON','verificationFlowContext','verificationFlowError',
  'openVerificationModal','closeVerificationModal','requestVerification','requestRecoveryCode','submitVerificationFlow',
  'openChangePwd','closeChangePwd','saveChangePwd','requestAccountDeletion','switchAuthTab',
  'openBindEmail','requestProfileEmailCode','saveEmail'].map(extract).join('\n');
const finalExport = {exported_at:'2026-09-19T00:00:00Z',account:{username:'synthetic-a'},archives:{notes:[]}};
function response(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>data};}
function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}
function fixture(options={}) {
  const nodes=new Map(),calls=[],toasts=[],tabs=[],pages=[],downloads=[],revoked=[];
  const counts={clear:0,accept:0,closeAuth:0,cooldown:0,confirm:0,prompt:0};
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',style:{display:'none'},textContent:'',placeholder:'',lastChild:{textContent:''},focus(){},closest(){return this;}});return nodes.get(id);};
  const defaults={
    '/auth/verification/request':{accepted:true,challenge_id:'challenge-synthetic',delivery:'sms'},
    '/auth/password-reset':{ok:true},'/auth/change-password':{ok:true},
    '/auth/login/otp':{token:'new-synthetic-session',user:{id:'owner-a'}},
    '/account':{ok:true,final_export:finalExport,primary_delete_by:'2026-10-19T00:00:00Z',backup_clear_by:'2026-12-18T00:00:00Z'},
  };
  const c=vm.createContext({console,Blob,Map,Date,API_AUTH:'https://synthetic.invalid',PUBLIC_PRODUCT:options.public!==false,
    _authUser:options.guest?null:{id:'owner-a'},_authToken:options.guest?null:'synthetic-token-a',_chatUserStateEpoch:1,
    _verificationMode:'login_phone',_verificationChallenge:null,_phoneCodeResendAt:0,_registerPhoneChallenge:null,_authTab:'login',
    document:{getElementById:node,body:{appendChild(){}},createElement:()=>({href:'',download:'',click(){if(options.click)options.click(c);downloads.push(this.download);},remove(){}})},
    URL:{createObjectURL(){if(options.objectURL)options.objectURL(c);return 'blob:synthetic';},revokeObjectURL:u=>revoked.push(u)},
    fetch:async(url,init={})=>{const route=url.replace('https://synthetic.invalid','');calls.push({route,init});return options.routes?.[route]?options.routes[route](init,c):response(defaults[route]);},
    showToast:message=>toasts.push(message),showPage:page=>pages.push(page),openAuthModal:tab=>tabs.push(tab),closeAuthModal(){counts.closeAuth++;},
    authClearLocalSession(){counts.clear++;c._authUser=null;c._authToken=null;c._chatUserStateEpoch++;},
    authAcceptSession(data){counts.accept++;c._authUser=data.user;c._authToken=data.token;c._chatUserStateEpoch++;},
    startPhoneCodeCooldown(){counts.cooldown++;c._phoneCodeResendAt=Date.now()+60000;},
    phoneCodePurpose:()=>c._authTab==='login'?'login_phone':'register_phone',syncPublicAuthAvailability(){},
    prompt:()=>{counts.prompt++;return options.prompt?options.prompt(c):'SyntheticPassword!123';},
    confirm:()=>{counts.confirm++;return options.confirm?options.confirm(c):true;},
  });
  c._chatOwnerId=()=>c._authUser?.id || null;
  c._chatIdentitySnapshot=()=>({ownerId:c._chatOwnerId(),epoch:c._chatUserStateEpoch});
  c._chatIdentityMatches=s=>!!s?.ownerId&&s.ownerId===c._chatOwnerId()&&s.epoch===c._chatUserStateEpoch;
  vm.runInContext(functions,c);
  const switchAccount=()=>{c._authUser={id:'owner-b'};c._authToken='synthetic-token-b';c._chatUserStateEpoch++;};
  const prepareReset=()=>{
    c.openVerificationModal('password_reset');node('verification-destination').value='13800138000';node('verification-code').value='123456';node('verification-new-password').value='SyntheticNew!123';
    c._verificationChallenge={id:'challenge-synthetic',channel:'phone',destination:'13800138000',purpose:'password_reset'};
  };
  const prepareChange=()=>{node('pwd-old').value='SyntheticOld!123';node('pwd-new').value='SyntheticNew!123';node('pwd-new2').value='SyntheticNew!123';};
  return {c,node,calls,toasts,tabs,pages,downloads,revoked,counts,switchAccount,prepareReset,prepareChange};
}

test('PUBLIC login retains original recovery actions; registration does not',()=>{
  const f=fixture();f.c.switchAuthTab('login');assert.equal(f.node('auth-recovery-actions').style.display,'flex');assert.equal(f.node('auth-password').style.display,'none');assert.equal(f.node('auth-submit-btn').textContent,'验证码登录');
  f.c.switchAuthTab('register');assert.equal(f.node('auth-recovery-actions').style.display,'none');
});
test('PUBLIC reset reuses original phone-only modal without sending SMS',()=>{
  const f=fixture();f.node('verification-channel').value='email';f.c.openVerificationModal('password_reset');assert.equal(f.node('verification-channel').value,'phone');assert.equal(f.node('verification-channel').style.display,'none');assert.equal(f.node('verification-new-password').style.display,'block');assert.equal(f.calls.length,0);
});
test('PUBLIC change-password entry opens reset and never auto-sends SMS',()=>{
  const f=fixture();f.c.openChangePwd();assert.equal(f.c._verificationMode,'password_reset');assert.equal(f.calls.length,0);
});
test('private original change-password form is preserved',()=>{
  const f=fixture({public:false});f.c.openChangePwd();assert.equal(f.node('profile-change-pwd-form').style.display,'flex');assert.equal(f.calls.length,0);
});
test('phone reset SMS request preserves purpose and accepted receipt',async()=>{
  const f=fixture({guest:true});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';await f.c.requestRecoveryCode();
  assert.deepEqual(JSON.parse(f.calls[0].init.body),{channel:'phone',destination:'13800138000',purpose:'password_reset'});assert.equal(f.c._verificationChallenge.purpose,'password_reset');assert.equal(f.counts.cooldown,1);
});
test('PUBLIC reset cannot send email even if hidden select is changed',async()=>{
  const f=fixture();f.c.openVerificationModal('password_reset');f.node('verification-channel').value='email';f.node('verification-destination').value='nobody@example.invalid';await f.c.requestRecoveryCode();assert.equal(f.calls.length,0);
});
test('SMS without accepted challenge is rejected; no fabricated challenge',async()=>{
  const f=fixture({routes:{'/auth/verification/request':()=>response({accepted:false,challenge_id:'bad'})}});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';await f.c.requestRecoveryCode();assert.equal(f.c._verificationChallenge,null);assert.match(f.node('verification-error').textContent,/未确认/);
});
test('SMS throttle and unknown outcome never auto-retry',async()=>{
  const f=fixture({routes:{'/auth/verification/request':()=>response({detail:'slow'},429)}});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';await f.c.requestRecoveryCode();await f.c.requestRecoveryCode();assert.equal(f.calls.length,1);assert.ok(f.counts.cooldown);assert.match(f.node('verification-error').textContent,/等待/);
});
test('duplicate in-flight SMS requests send once',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/verification/request':()=>gate.promise}});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';const pending=f.c.requestRecoveryCode();await f.c.requestRecoveryCode();assert.equal(f.calls.length,1);gate.resolve(response({accepted:true,challenge_id:'id',delivery:'sms'}));await pending;
});
test('changing destination before SMS response cannot bind old challenge',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/verification/request':()=>gate.promise}});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';const pending=f.c.requestRecoveryCode();f.node('verification-destination').value='13900139000';gate.resolve(response({accepted:true,challenge_id:'id',delivery:'sms'}));await pending;assert.equal(f.c._verificationChallenge,null);assert.match(f.node('verification-error').textContent,/联系方式已变化/);
});
test('closed or reopened reset ignores late challenge',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/verification/request':()=>gate.promise}});f.c.openVerificationModal('password_reset');f.node('verification-destination').value='13800138000';const pending=f.c.requestRecoveryCode();f.c.closeVerificationModal();f.c.openVerificationModal('password_reset');gate.resolve(response({accepted:true,challenge_id:'id',delivery:'sms'}));await pending;assert.equal(f.c._verificationChallenge,null);assert.equal(f.toasts.length,0);
});
test('guest reset confirms HTTP plus ok:true then clears local state and returns OTP login',async()=>{
  const f=fixture({guest:true});f.prepareReset();await f.c.submitVerificationFlow();assert.equal(f.calls[0].route,'/auth/password-reset');assert.equal(f.calls[0].init.cache,'no-store');assert.deepEqual(JSON.parse(f.calls[0].init.body),{channel:'phone',destination:'13800138000',challenge_id:'challenge-synthetic',code:'123456',new_password:'SyntheticNew!123'});
  assert.equal(f.counts.clear,1);assert.deepEqual(f.tabs,['login']);assert.equal(f.node('verification-new-password').value,'');assert.equal(f.node('verification-code').value,'');assert.equal(f.c._verificationChallenge,null);
});
for(const [label,result] of [['HTTP failure',response({ok:true,detail:'rejected'},400)],['ok false',response({ok:false})],['malformed JSON',{ok:true,status:200,json:async()=>{throw Error('bad JSON');}}]]) {
  test('reset '+label+' does not claim success or log out',async()=>{
    const f=fixture({routes:{'/auth/password-reset':()=>result}});f.prepareReset();await f.c.submitVerificationFlow();assert.equal(f.counts.clear,0);assert.equal(f.tabs.length,0);assert.equal(f.node('verification-error').style.display,'block');
  });
}
test('reset rejects challenge for wrong purpose or changed destination',async()=>{
  const f=fixture();f.prepareReset();f.c._verificationChallenge.purpose='login_phone';await f.c.submitVerificationFlow();assert.equal(f.calls.length,0);f.prepareReset();f.node('verification-destination').value='13900139000';await f.c.submitVerificationFlow();assert.equal(f.calls.length,0);
});
test('reset unknown outcome invalidates local challenge and cannot blindly resubmit',async()=>{
  const f=fixture({routes:{'/auth/password-reset':()=>{throw Error('network lost');}}});f.prepareReset();await f.c.submitVerificationFlow();await f.c.submitVerificationFlow();assert.equal(f.calls.length,1);assert.equal(f.c._verificationChallenge,null);assert.equal(f.counts.clear,0);
});
test('duplicate in-flight reset sends only one mutation',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/password-reset':()=>gate.promise}});f.prepareReset();const pending=f.c.submitVerificationFlow();await f.c.submitVerificationFlow();assert.equal(f.calls.length,1);gate.resolve(response({ok:true}));await pending;
});
test('late reset cannot log out another account',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/password-reset':()=>gate.promise}});f.prepareReset();const pending=f.c.submitVerificationFlow();f.switchAccount();gate.resolve(response({ok:true}));await pending;assert.equal(f.counts.clear,0);assert.equal(f.toasts.length,0);assert.equal(f.c._authUser.id,'owner-b');
});
test('unchanged original OTP login still accepts valid session contract',async()=>{
  const f=fixture({guest:true});f.c.openVerificationModal('login_phone');f.node('verification-destination').value='13800138000';f.node('verification-code').value='123456';f.c._verificationChallenge={id:'id',channel:'phone',destination:'13800138000',purpose:'login_phone'};await f.c.submitVerificationFlow();assert.equal(f.calls[0].route,'/auth/login/otp');assert.equal(f.counts.accept,1);assert.equal(f.counts.closeAuth,1);
});
test('existing old-password change uses captured bearer and clears passwords after confirmed success',async()=>{
  const f=fixture();f.prepareChange();await f.c.saveChangePwd();assert.equal(f.calls[0].route,'/auth/change-password');assert.equal(f.calls[0].init.headers.Authorization,'Bearer synthetic-token-a');assert.equal(f.counts.clear,1);assert.equal(f.node('pwd-old').value,'');assert.equal(f.node('pwd-new').value,'');assert.deepEqual(f.tabs,['login']);
});
test('old-password change rejects ok:false and unknown without session clear or retry',async()=>{
  const f=fixture({routes:{'/auth/change-password':()=>response({ok:false})}});f.prepareChange();await f.c.saveChangePwd();assert.equal(f.counts.clear,0);assert.equal(f.calls.length,1);assert.match(f.toasts.at(-1),/未确认/);
});
test('late change-password response never logs out another account',async()=>{
  const gate=deferred(),f=fixture({routes:{'/auth/change-password':()=>gate.promise}});f.prepareChange();const pending=f.c.saveChangePwd();f.switchAccount();gate.resolve(response({ok:true}));await pending;assert.equal(f.counts.clear,0);assert.equal(f.c._authUser.id,'owner-b');
});
test('account deletion retains password and confirmation plus final export before local logout',async()=>{
  const f=fixture();await f.c.requestAccountDeletion();assert.equal(f.counts.prompt,1);assert.equal(f.counts.confirm,1);assert.equal(f.calls[0].init.method,'DELETE');assert.equal(f.calls[0].init.cache,'no-store');assert.deepEqual(JSON.parse(f.calls[0].init.body),{password:'SyntheticPassword!123',include_final_export:true});assert.deepEqual(f.downloads,['noteai-final-account-export.json']);assert.equal(f.counts.clear,1);assert.equal(f.revoked.length,1);assert.deepEqual(f.pages,['landing']);assert.match(f.toasts.at(-1),/账户访问已撤销.*2026-10-19.*2026-12-18/);assert.doesNotMatch(f.toasts.at(-1),/全部数据.*立即删除/);
});
test('account deletion cancellation cannot invoke endpoint',async()=>{
  const f=fixture({confirm:()=>false});await f.c.requestAccountDeletion();assert.equal(f.calls.length,0);assert.equal(f.counts.clear,0);
});
for(const [label,result] of [['HTTP 409',response({ok:true,detail:'in flight'},409)],['ok false',response({ok:false})],['malformed success',{ok:true,status:200,json:async()=>{throw Error('bad JSON');}}]]) {
  test('account deletion '+label+' preserves local session and does not download',async()=>{
    const f=fixture({routes:{'/account':()=>result}});await f.c.requestAccountDeletion();assert.equal(f.counts.clear,0);assert.equal(f.downloads.length,0);assert.match(f.toasts.at(-1),/失败|未确认/);
  });
}
test('unknown deletion performs no automatic retry or local success',async()=>{
  const f=fixture({routes:{'/account':()=>{throw Error('network lost');}}});await f.c.requestAccountDeletion();assert.equal(f.calls.length,1);assert.equal(f.counts.clear,0);assert.match(f.toasts.at(-1),/结果未确认/);
});
test('confirmed deletion remains confirmed when final export is missing',async()=>{
  const f=fixture({routes:{'/account':()=>response({ok:true})}});await f.c.requestAccountDeletion();assert.equal(f.counts.clear,1);assert.equal(f.downloads.length,0);assert.match(f.toasts.at(-1),/注销申请已提交.*导出未完成/);
});
test('download failure cannot leave a deleted account marked locally logged in',async()=>{
  const f=fixture({click:()=>{throw Error('blocked');}});await f.c.requestAccountDeletion();assert.equal(f.counts.clear,1);assert.equal(f.revoked.length,1);assert.match(f.toasts.at(-1),/注销申请已提交.*导出未完成/);
});
test('late account deletion response cannot download old data or log out new account',async()=>{
  const gate=deferred(),f=fixture({routes:{'/account':()=>gate.promise}});const pending=f.c.requestAccountDeletion();f.switchAccount();gate.resolve(response({ok:true,final_export:finalExport}));await pending;assert.equal(f.counts.clear,0);assert.equal(f.downloads.length,0);assert.equal(f.toasts.length,0);
});
test('identity is rechecked directly before final-export download',async()=>{
  const f=fixture({objectURL:c=>{c._authToken='other-session';}});await f.c.requestAccountDeletion();assert.equal(f.downloads.length,0);assert.equal(f.counts.clear,0);assert.equal(f.revoked.length,1);
});

test('actual account-state clear hook removes both original sensitive forms',()=>{
  const stateClear = extract('chatClearUserState');
  assert.match(stateClear,/\bcloseVerificationModal\(\)/);
  assert.match(stateClear,/\bcloseChangePwd\(\)/);
});
test('closing verification clears phone, code, new password and challenge',()=>{
  const f=fixture();f.prepareReset();f.c.closeVerificationModal();
  for(const id of ['verification-destination','verification-code','verification-new-password'])assert.equal(f.node(id).value,'');
  assert.equal(f.c._verificationChallenge,null);assert.equal(f.node('verification-modal').style.display,'none');
});
test('closing original change-password form clears all three secrets',()=>{
  const f=fixture();f.prepareChange();f.c.closeChangePwd();
  for(const id of ['pwd-old','pwd-new','pwd-new2'])assert.equal(f.node(id).value,'');
  assert.equal(f.node('profile-change-pwd-form').style.display,'none');
});

for (const action of ['openBindEmail','requestProfileEmailCode','saveEmail']) {
  test('PUBLIC '+action+' reports unavailable email delivery without a request or local profile change',async()=>{
    const f=fixture();f.c._authUser.email='original@example.invalid';
    f.node('profile-email-input').value='synthetic@example.invalid';f.node('profile-email-code').value='123456';
    f.c._profileEmailChallenge={id:'synthetic-email',destination:'synthetic@example.invalid'};
    await f.c[action]();
    assert.equal(f.calls.length,0);assert.equal(f.c._authUser.email,'original@example.invalid');
    assert.equal(f.node('profile-bind-email-form').style.display,'none');
    assert.match(f.toasts.at(-1),/邮箱验证码发送尚未接通/);
  });
}
