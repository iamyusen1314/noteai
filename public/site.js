'use strict';
const el = id => document.getElementById(id);
const contractVersion = 'account-access-2026-09-12';
let challenge = null;
let token = '';
try { token = sessionStorage.getItem('noteai_account_session') || ''; } catch (_) { /* Private browsing may deny storage; use this page's memory only. */ }
function saveSession(value) {
  token = value;
  try {
    if (value) sessionStorage.setItem('noteai_account_session', value);
    else sessionStorage.removeItem('noteai_account_session');
  } catch (_) { /* Account access can still use an in-memory session. */ }
}
let sending = false;
let submitting = false;
let cooldownUntil = 0;

async function api(path, body) {
  const headers = {'Content-Type': 'application/json'};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers,
    body: body === undefined ? undefined : JSON.stringify(body), credentials: 'omit', cache: 'no-store',
    signal: AbortSignal.timeout(15000)});
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : '操作未完成，请检查输入或稍后再试');
    error.status = response.status;
    throw error;
  }
  return result;
}

function invalidateChallenge() { challenge = null; el('code').value = ''; }
el('phone').addEventListener('input', invalidateChallenge);
el('auth-mode').addEventListener('change', () => {
  invalidateChallenge();
  el('submit-auth').textContent = el('auth-mode').value === 'register_phone' ? '验证并注册' : '验证并登录';
});

async function showAccount() {
  if (!token) return;
  try {
    const user = await api('/auth/me');
    el('account-phone').textContent = user.phone_masked;
    el('account-created').textContent = new Date(user.created_at).toLocaleString('zh-CN');
    el('my-account').hidden = false;
    el('auth-form').hidden = true;
  } catch (error) {
    if (error.status === 401) {
      saveSession('');
    }
    el('auth-message').textContent = error.message;
  }
}

el('send-code').addEventListener('click', async () => {
  if (sending || Date.now() < cooldownUntil) return;
  if (!el('phone').reportValidity()) return;
  if (!el('consent').checked) { el('auth-message').textContent = '请先阅读并同意账户服务条款和隐私说明。'; return; }
  sending = true; el('send-code').disabled = true; invalidateChallenge();
  const phone = el('phone').value, purpose = el('auth-mode').value;
  try {
    const result = await api('/auth/verification/request', {channel: 'phone', destination: phone, purpose});
    if (phone === el('phone').value && purpose === el('auth-mode').value) challenge = {id: result.challenge_id, phone, purpose};
    cooldownUntil = Date.now() + 60000;
    el('auth-message').textContent = result.delivery === 'sms_unknown'
      ? '发送结果暂未确认。如已收到验证码，可继续验证；页面不会自动重发。'
      : '验证码发送请求已受理，请查看本人手机短信。';
  } catch (error) {
    cooldownUntil = Date.now() + 60000;
    el('auth-message').textContent = error.name === 'TimeoutError' ? '发送结果暂不明确，请稍后再试；页面不会自动重发。' : error.message;
  } finally { sending = false; }
});
setInterval(() => {
  const seconds = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
  el('send-code').textContent = seconds ? `${seconds} 秒后可重发` : '获取验证码';
  el('send-code').disabled = sending || seconds > 0;
}, 1000);

el('auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (submitting || !el('auth-form').reportValidity()) return;
  if (!challenge || challenge.phone !== el('phone').value || challenge.purpose !== el('auth-mode').value) {
    el('auth-message').textContent = '请先为当前手机号和操作获取验证码。'; return;
  }
  submitting = true; el('submit-auth').disabled = true;
  try {
    const registration = challenge.purpose === 'register_phone';
    const body = {phone: challenge.phone, challenge_id: challenge.id, code: el('code').value};
    if (registration) { body.contract_version = contractVersion; body.privacy_accepted = el('consent').checked; }
    const result = await api(registration ? '/auth/register/otp' : '/auth/login/otp', body);
    saveSession(result.token);
    invalidateChallenge(); el('auth-message').textContent = registration ? '注册成功，现可使用账户服务。' : '已登录。';
    await showAccount();
  } catch (error) {
    el('auth-message').textContent = error.name === 'TimeoutError' ? '结果暂不明确，请使用登录功能核实；页面不会自动重复提交。' : error.message;
  } finally { submitting = false; el('submit-auth').disabled = false; }
});

el('logout').addEventListener('click', async () => {
  el('logout').disabled = true;
  try {
    try { await api('/auth/logout', {}); } catch (error) {
      if (error.status !== 401) throw error; // A revoked/expired session is already logged out.
    }
    saveSession('');
    el('my-account').hidden = true; el('auth-form').hidden = false;
    el('auth-message').textContent = '已退出登录。';
  } catch (error) { el('auth-message').textContent = '退出尚未确认，请重试以撤销服务器会话。'; }
  finally { el('logout').disabled = false; }
});

(async () => {
  try {
    const status = await api('/public/status');
    const open = status.registration_open === true && status.contract_version === contractVersion;
    el('registration-status').textContent = open ? '已开放' : '暂未开放';
    el('auth-availability').textContent = open ? '可使用本人手机号获取验证码。' : '短信注册服务尚未开放，您仍可浏览官网或联系客服。';
    el('auth-fields').disabled = !open;
  } catch (_) {
    el('registration-status').textContent = '暂不可用';
    el('auth-availability').textContent = '账户服务暂不可用，您仍可浏览官网或联系客服。';
  }
  await showAccount();
})();

// All example content remains readable without JavaScript or a working account API.
const demoButtons = Array.from(document.querySelectorAll('[data-demo]'));
function selectDemo(name) {
  for (const button of demoButtons) {
    const selected = button.dataset.demo === name;
    button.setAttribute('aria-pressed', String(selected));
    button.classList.toggle('secondary', !selected);
    el('demo-' + button.dataset.demo).hidden = !selected;
  }
}
for (const button of demoButtons) button.addEventListener('click', () => selectDemo(button.dataset.demo));
selectDemo('input');
