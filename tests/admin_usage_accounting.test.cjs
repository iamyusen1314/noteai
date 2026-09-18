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
  'adminKnownCount', 'adminKnownMoney', 'adminKnownTokens', 'adminCostCoverage',
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
  assert.match(result, /结果未知 1 · 进行中 0 · 用量缺失 1/);
  assert.match(result, /历史没有步骤明细/);
  assert.doesNotMatch(result, /¥3\.7500/);
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
