const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const React = require('react');
const { renderToStaticMarkup: render } = require('react-dom/server');
const { ResultView } = require('./HostedResult.tsx');
const { ResultReportSummary, resultReportHtml } = require('./ResultReport.tsx');
const { ComparisonResults } = require('./UX1Comparison.tsx');
const { resultBrowserSummary, resultBrowserItem, gradeSummary, matchesResultFilters } = require('./resultModel.ts');
const load = name => JSON.parse(fs.readFileSync(path.join(__dirname, '../../../test/fixtures', name)));
const current = load('w21/confirmed-majority.result.json');
const legacy = load('w12/lg.result.json');

function checkCurrent(result) {
  const before = JSON.stringify(result);
  const counts = resultBrowserSummary(result);
  assert.equal(counts.provisional, 0);
  assert.equal(counts.total, counts.confirmed + counts.hold);
  const screen = render(React.createElement(ResultView, { result, runStatus: 'completed' }));
  assert.doesNotMatch(screen, /잠정|이전 버전 결과|value="provisional"|provisional-key/);
  const summary = render(React.createElement(ResultReportSummary, { result }));
  assert.equal((summary.match(/<strong>/g) || []).length, 2);
  assert.ok(screen.includes(`확정 ${counts.confirmed} + 보류 ${counts.hold} = 추출 주장 ${counts.total}건`));
  for (const grade of ['E3', 'E2', 'E1', 'E0']) assert.ok(summary.includes(`aria-label="${grade} 확정 ${counts.confirmedGrades[grade]}건"`));
  for (const claim of result.claims) {
    assert.doesNotMatch(render(React.createElement(ResultView, { result: { ...result, claims: [claim] } })), /잠정/);
  }
  for (const reportMode of ['summary', 'full']) {
    const html = resultReportHtml(result, { reportMode, runStatus: 'completed' });
    assert.doesNotMatch(html, /잠정|이전 버전 결과|<th>추가 확인 필요<\/th>/);
    assert.ok(html.includes(`전체 ${counts.total}건 · 확정 ${counts.confirmed}건 · 보류 ${counts.hold}건`));
    if (reportMode === 'full') assert.equal((html.match(/<article data-claim-id=/g) || []).length, counts.total);
  }
  const comparison = render(React.createElement(ComparisonResults, { reports: [{result, name:'보고서', runId:'a', pages:[], pageCount:150}] }));
  assert.doesNotMatch(comparison, /잠정|이전 버전 결과/);
  assert.equal(JSON.stringify(result), before);
}

test('UX3 current results have only confirmed and held states across every claim, accessible labels and both PDFs', () => checkCurrent(current));
test('UX3 stale presentation metadata does not leak into current exports or change source records', () => {
  const result = structuredClone(current);
  result.claims[0].provisional_grade = { evidence_grade:'E1', display:'잠정·미확정', reason:'needs_review', hold_reasons:['과거 보류 사유'] };
  assert.match(resultReportHtml(result), /과거 보류 사유/);
  checkCurrent(result);
});
test('UX3 older claims stay distinct, filterable and unconfirmed with exact totals', () => {
  const before = JSON.stringify(legacy), counts = resultBrowserSummary(legacy);
  assert.ok(counts.provisional > 0);
  assert.equal(counts.total, counts.confirmed + counts.provisional + counts.hold);
  const screen = render(React.createElement(ResultView, {result:legacy}));
  assert.match(screen, /이전 버전 결과/);
  assert.match(screen, /추가 확인 필요/);
  assert.doesNotMatch(screen, /잠정/);
  for (const claim of legacy.claims) {
    const item = resultBrowserItem(legacy, claim);
    if (item.bucket !== 'provisional') continue;
    assert.equal(item.confirmed, false);
    assert.equal(gradeSummary(claim).confirmed, false);
    assert.match(item.badge, /^추가 확인 필요 · E[0-3]$/);
    assert.ok(matchesResultFilters(item, {queue:'provisional', status:'provisional', grade:'all', track:'all', search:''}));
    assert.ok(!matchesResultFilters(item, {queue:'hold', status:'all', grade:'all', track:'all', search:''}));
  }
  for (const reportMode of ['summary', 'full']) assert.match(resultReportHtml(legacy, {reportMode}), /이전 버전 결과/);
  assert.equal(JSON.stringify(legacy), before);
});
test('UX3 status and help copy contain no retired label', () => {
  for (const name of ['HostedAnalysis.tsx','hostedClient.ts','HostedResult.tsx','ResultReport.tsx','HostedExamples.tsx','MyReports.tsx','UX1Comparison.tsx','UX1Insights.tsx','UX1Progress.tsx','ux1Model.ts','resultModel.ts']) {
    assert.doesNotMatch(fs.readFileSync(path.join(__dirname,name),'utf8'), /잠정/, name);
  }
});
if (process.env.UX3_REAL_DATA_DIR) {
  for (const file of ['E23/lg.w18-result.json','E23/kakao.w18-result.json','PR1/hynix.result.json','PR1/hyundai.result.json','PR1/naver.result.json','PR1/samsung.result.json','PR1/lge.result.json']) {
    test(`UX3 saved v29d real data: ${file}`, () => checkCurrent(JSON.parse(fs.readFileSync(path.join(process.env.UX3_REAL_DATA_DIR,file)))));
  }
}
