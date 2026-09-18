const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const html = fs.readFileSync(path.join(__dirname, '../model/admin.html'), 'utf8');
function source(name) {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `actual function ${name} is present`);
  return match[0];
}
const names = ['esc', 'fmtTokens', 'adminFiniteNumber', 'adminIsNonNegativeInteger',
  'adminKnownCount', 'adminKnownMoney', 'adminRecordedCostBreakdown', 'adminKnownTokens', 'adminCostCoverage',
  'adminCoverageCountsText', 'adminCoverageHeadline', 'adminAccountingSummary', 'adminUsageTooltip'];
const functions = vm.createContext({});
new vm.Script(names.map(source).join('\n')).runInContext(functions);
const coverage = {total_records: 2, strict_actual_records: 1, included_in_parent_records: 1,
  legacy_unverifiable_records: 0, partial_records: 0, unpriced_records: 0,
  usage_incomplete_records: 0, actual_margin_ready: true};
const window = {kind: 'calendar_month', timezone: 'UTC', start: '2026-09-01T00:00:00+00:00',
  end: '2026-10-01T00:00:00+00:00', as_of: '2026-09-19T00:00:00+00:00'};

test('all actual inline JavaScript parses without executing the page', () => {
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length);
  for (const script of scripts) new vm.Script(script[1]);
});

test('legacy margin flag cannot override absent, unknown or incomplete model accounting', () => {
  for (const accounting of [null, {}, {cost: {}}, {cost: {complete: false}}, {cost: {complete: 'true'}}]) {
    assert.equal(functions.adminCostCoverage(coverage, accounting).ready, false);
  }
  const complete = functions.adminCostCoverage(coverage, {cost: {complete: true,
    supplier_bill_paid_rmb: null, platform_total_rmb: null}});
  assert.equal(complete.ready, true); // This is model usage completeness only.
  const headline = functions.adminCoverageHeadline(complete, 'UTC自然月',
    '仅为模型计量口径，非结算费用', '不可宣称实际毛利');
  assert.match(headline, /非结算费用/);
  assert.doesNotMatch(headline, /可使用实际毛利/);
});

test('malformed or internally inconsistent coverage remains unavailable', () => {
  for (const raw of [null, [], {...coverage, total_records: '2'},
    {...coverage, strict_actual_records: true}, {...coverage, included_in_parent_records: 0},
    {...coverage, total_records: -1}, {...coverage, total_records: Number.MAX_SAFE_INTEGER + 1}]) {
    const result = functions.adminCostCoverage(raw, {cost: {complete: true}});
    assert.equal(result.ready, false);
    assert.equal(result.state, 'unavailable');
  }
});

test('unknown numeric evidence is not coerced into a confirmed zero', () => {
  for (const value of [null, undefined, '', '0', true, NaN, Infinity, -1]) {
    assert.equal(functions.adminKnownMoney(value), '待核实');
    assert.equal(functions.adminKnownCount(value), '待核实');
    assert.equal(functions.adminKnownTokens(value), '待核实');
  }
  assert.equal(functions.adminKnownMoney(0), '¥0.0000');
  assert.equal(functions.adminKnownCount(0), '0');
  assert.equal(functions.adminKnownTokens(0), '0');
  const summary = functions.adminAccountingSummary({cost: {supplier_bill_paid_rmb: null,
    platform_total_rmb: null}}, window);
  assert.match(summary, /供应商实付 待核实 · 平台总成本 待核实/);
  assert.doesNotMatch(summary, /¥0\.0000/);
});

test('summary distinguishes known, manual, estimated and unknown amounts without double summing', () => {
  const result = functions.adminAccountingSummary({cost: {known_calculated_rmb: 1.25,
    manual_cost_rmb: 0.5, estimated_only_rmb: 2, unknown_records: 3,
    supplier_bill_paid_rmb: null, platform_total_rmb: null},
    business: {recorded: 4, completed: 1, failed: 1, waiting_for_input: 1, status_unknown: 1},
    models: {usage_records: 8}, physical: {recorded: 9, unknown: 1, in_flight: 0, usage_missing: 1},
    local_steps: {status: 'not_recorded'}}, window);
  assert.match(result, /已知模型计量成本 ¥1\.2500 · 手工记录 ¥0\.5000 · 仅估算 ¥2\.0000 · 未知 3 条/);
  assert.match(result, /状态未记录 1/);
  assert.match(result, /不等于实际 HTTP 次数/);
  assert.match(result, /预留记录状态（互斥，合计 9 条）：已记录终态 待核实 · 处理中 0 · 结果未知 1 · 其他状态 待核实/);
  assert.match(result, /记录完整性（与以上状态重叠，不另加到预留总数）：有 HTTP 状态 待核实 · 未记录有效 HTTP 状态 待核实 · 缺模型用量关联 1/);
  assert.match(result, /历史没有步骤明细/);
  assert.doesNotMatch(result, /¥3\.7500/);
});

test('reservation states and overlapping completeness counts are not presented as an extra request', () => {
  const accounting = {physical: {recorded: 823, responded: 818, in_flight: 0, unknown: 5,
    state_unrecognized: 0, http_responses_observed: 822, not_dispatched_or_unconfirmed: 1,
    usage_missing: 0, actual_http_requests: null}};
  const before = JSON.stringify(accounting);
  const result = functions.adminAccountingSummary(accounting, window);
  assert.match(result, /预留记录状态（互斥，合计 823 条）：已记录终态 818 · 处理中 0 · 结果未知 5 · 其他状态 0<br\/>/);
  assert.match(result, /记录完整性（与以上状态重叠，不另加到预留总数）：有 HTTP 状态 822 · 未记录有效 HTTP 状态 1 · 缺模型用量关联 0<br\/>/);
  assert.match(result, /实际 HTTP 请求次数 待核实（预留记录不能还原实际发送次数）/);
  assert.doesNotMatch(result, /824|已响应|未发出或未确认|用量缺失/);
  assert.equal(JSON.stringify(accounting), before);
});

test('call details do not turn a terminal reservation without HTTP status into an actual response', () => {
  const context = vm.createContext({});
  new vm.Script(['esc', 'adminLedgerLabel', 'adminLedgerTime', 'renderAdminCallDetails'].map(source).join('\n')).runInContext(context);
  const render = state => context.renderAdminCallDetails({status: 'available', calls: [
    {state, http_status: null, binding: 'physical_call'}]});
  assert.match(render('responded'), /已记录终态（不等于实际 HTTP 响应或业务成功）/);
  assert.match(render('responded'), /HTTP 未知/);
  assert.doesNotMatch(render('responded'), /收到响应/);
  assert.match(render('dispatched'), /预留处理中，结果待确认/);
  assert.doesNotMatch(render('dispatched'), /已派发/);
});

test('dashboard cost separates known 83.7313 and estimated 3.0400 without relabelling the legacy total', () => {
  const accounting = {cost: {known_calculated_rmb: 83.7313, manual_cost_rmb: 0, estimated_only_rmb: 3.04}};
  const before = JSON.stringify(accounting);
  assert.equal(functions.adminRecordedCostBreakdown(accounting),
    '已知模型计量 ¥83.7313 · 手工记录 ¥0.0000 · 仅估算 ¥3.0400');
  assert.equal(functions.adminKnownMoney(86.7713), '¥86.7713');
  assert.equal(JSON.stringify(accounting), before);
  assert.equal(functions.adminRecordedCostBreakdown({}),
    '已知模型计量 待核实 · 手工记录 待核实 · 仅估算 待核实');
  assert.match(source('loadDashboard'), /adminKnownMoney\(f\.api_cost\)/);
  assert.match(source('loadDashboard'), /adminRecordedCostBreakdown\(d\.usage\?\.accounting\)/);
  assert.match(source('loadDashboard'), /return adminUsageTooltip\(op\)/);
  assert.match(html, /本月已记录成本/);
  assert.match(html, /含估算，非供应商账单/);
  assert.doesNotMatch(html, /本月 API 成本/);
});

test('user list mixed record counts and costs preserve 56 and 86.7713 with explicit labels', async () => {
  const nodes = new Map();
  const document = {getElementById: key => {
    if (!nodes.has(key)) nodes.set(key, {value: '', textContent: '', innerHTML: ''});
    return nodes.get(key);
  }};
  const response = {total: 1, users: [{id: 'synthetic', username: 'synthetic', month_ops: 56,
    month_tokens: 100, month_cost: 86.7713, credits: 0}]};
  const context = vm.createContext({document, URLSearchParams, _userPage: 1,
    aFetch: async () => ({json: async () => response})});
  new vm.Script(['esc', 'fmtTokens', 'adminFiniteNumber', 'adminIsNonNegativeInteger',
    'adminKnownCount', 'adminKnownMoney', 'loadUsers'].map(source).join('\n')).runInContext(context);
  await context.loadUsers();
  let result = nodes.get('users-tbody').innerHTML;
  assert.match(result, /<td>56<\/td>/);
  assert.match(result, /¥86\.7713/);
  assert.doesNotMatch(result, /已知模型计量|仅估算|52|83\.7313/);
  assert.match(html, /本月操作记录<br\/><small>含附加事件/);
  assert.match(html, /本月已记录成本<br\/><small>含估算，非供应商账单/);
  response.users[0].month_ops = null;
  response.users[0].month_cost = null;
  await context.loadUsers();
  result = nodes.get('users-tbody').innerHTML;
  assert.match(result, /<td>待核实<\/td>/);
  assert.doesNotMatch(result, /¥0\.0000/);
});

function ledgerContext() {
  const context = vm.createContext({});
  const constants = ['OPERATION', 'SOURCE', 'COST_MODE', 'TXN_TYPE', 'PACKAGE'].map(name => {
    const match = html.match(new RegExp(`const ADMIN_LEDGER_${name}_LABELS = Object\\.freeze\\(\\{[^]*?\\n\\}\\);`));
    assert.ok(match);
    return match[0];
  });
  new vm.Script(constants.join('\n') + '\n' + ['esc', 'fmtTokens', 'adminFiniteNumber',
    'adminIsNonNegativeInteger', 'adminKnownCount', 'adminKnownMoney', 'adminKnownTokens',
    'adminLedgerNumber', 'adminLedgerLabel', 'adminLedgerTime', 'renderAdminCallDetails',
    'renderAdminUsageLedger', 'renderAdminCreditLedger'].map(source).join('\n')).runInContext(context);
  return context;
}

test('usage ledger labels 36 model records and never infers zero requests from missing or included detail', () => {
  const context = ledgerContext();
  const row = {operation: 'generate', model_calls: 36, model_names: 'recorded-model',
    tokens_in: 120, tokens_out: 20, cost_rmb: 1, credits_used: 8};
  const recorded = context.renderAdminUsageLedger([row]);
  assert.match(recorded, /36 条模型用量记录（非 HTTP 次数）/);
  assert.match(recorded, /已记录：入 120 \/ 出 20；不证明用量完整/);
  const missing = context.renderAdminUsageLedger([{...row, model_calls: 0, tokens_in: 0,
    tokens_out: 0, model_names: '', cost_mode: 'estimated'}]);
  assert.match(missing, /未保留模型用量记录，不能据此判断未请求/);
  assert.match(missing, /未保留独立明细，不能据此判断实际为零/);
  assert.doesNotMatch(missing, /0 次模型调用|入 0 \/ 出 0/);
  const included = context.renderAdminUsageLedger([{...row, model_calls: 0, tokens_in: 0,
    tokens_out: 0, cost_mode: 'included_in_parent'}]);
  assert.match(included, /附加事件，模型用量计入主任务/);
  assert.match(included, /计入主任务，本条没有独立明细/);
  assert.doesNotMatch(included, /0 次模型调用|入 0 \/ 出 0/);
  const invalid = context.renderAdminUsageLedger([{...row, model_calls: null, tokens_in: null, tokens_out: null}]);
  assert.match(invalid, /模型用量记录数待核实/);
  assert.doesNotMatch(invalid, /0 次模型调用|入 0 \/ 出 0/);
});

test('wallet ledger names only the confirmed payment refund enum and preserves its recorded debit', () => {
  const context = ledgerContext();
  const row = {type: 'payment_refund', amount: -100, balance_after: 50, paid_rmb: -10,
    description: '支付退款：积分包撤销'};
  const before = JSON.stringify(row);
  const result = context.renderAdminCreditLedger([row]);
  assert.match(result, /<b>支付退款：积分包撤销<\/b>/);
  assert.match(result, /-100\.0 积分/);
  assert.match(result, /余额 50\.0/);
  assert.equal(JSON.stringify(row), before);
  assert.match(context.renderAdminCreditLedger([{...row, type: 'unrecognized'}]), /未知变动/);
});

test('summary and chart tooltip escape HTML and never trust string counts as markup', () => {
  const payload = '<img src=x onerror="globalThis.leak()">';
  const summary = functions.adminAccountingSummary({business: {recorded: payload}, cost: {}},
    {...window, start: payload, as_of: payload});
  const tooltip = functions.adminUsageTooltip({label: payload, count: payload, total_tokens: null, cost: null});
  for (const value of [summary, tooltip]) {
    assert.doesNotMatch(value, /<img/);
    assert.match(value, /&lt;img/);
    assert.match(value, /&quot;/);
    assert.match(value, /待核实/);
  }
});

test('calendar period is explicit and an unrecognized timezone is not labelled UTC', () => {
  assert.match(functions.adminAccountingSummary({}, window), /UTC自然月/);
  assert.match(functions.adminAccountingSummary({}, {...window, kind: 'rolling_days'}), /UTC滚动周期/);
  const unknown = functions.adminAccountingSummary({}, {...window, timezone: 'Asia/Shanghai'});
  assert.match(unknown, /统计时区待核实/);
  assert.doesNotMatch(unknown, /UTC自然月/);
  assert.match(source('loadUsage'), /usage-stats\?period=calendar_month/);
  assert.match(html, /各操作用量记录（UTC自然月）/);
  assert.doesNotMatch(html, /各操作调用量（近30天）/);
});

test('actual page uses correct overview contract and avoids supplier-settled or per-record completeness claims', () => {
  assert.match(source('loadDashboard'), /adminCostCoverage\(f\.coverage, d\.usage\?\.accounting\)/);
  assert.match(source('loadUsage'), /adminUsageTooltip\(op\)/);
  assert.match(source('renderAdminUsageLedger'), /adminKnownMoney\(row\?\.cost_rmb\)/);
  assert.match(html, /旧模型计量金额（不证明本条请求完整结算）/);
  assert.match(html, /模型计量差额率（最近30日，未结算）/);
  assert.doesNotMatch(html, /综合毛利率（最近30日）/);
});
