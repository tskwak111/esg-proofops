const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const ts = require('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { resultReportHtml, ResultReportSummary } = require('./ResultReport.tsx');
const { resultBrowserSummary, resultBrowserItem, claimEvidenceLine } = require('./resultModel.ts');
const { ResultView } = require('./HostedResult.tsx');
const load = path => JSON.parse(fs.readFileSync(`${__dirname}/../../../test/fixtures/${path}`));
const legacy = load('w12/lg.result.json');
const scoped = load('w20/scope-confirmation.result.json');

test('chart separates confirmed and provisional grades without changing API claims', () => {
  const result = { ...legacy, claims: [...legacy.claims, ...scoped.claims] };
  const before = JSON.stringify(result);
  const counts = resultBrowserSummary(result);
  assert.equal(Object.values(counts.confirmedGrades).reduce((a,b)=>a+b,0), counts.confirmed);
  assert.equal(Object.values(counts.grades).reduce((a,b)=>a+b,0), counts.provisional);
  assert.equal(counts.confirmed + counts.provisional + counts.hold, counts.total);
  const html = renderToStaticMarkup(React.createElement(ResultReportSummary, { result, companyName:'검증 기업',pageCount:150 }));
  for(const grade of ['E3','E2','E1','E0']) assert.ok(html.includes(`${grade} 확정 ${counts.confirmedGrades[grade]}건, 추가 확인 필요 ${counts.grades[grade]}건`));
  assert.ok(html.includes('검증 기업'));
  assert.equal(JSON.stringify(result), before);
});

test('export contains every claim, precise quote, grade and citation including rows beyond pagination', () => {
  const html = resultReportHtml(legacy,{reportName:'LG 결과',pageCount:150,runId:'existing-run'});
  assert.equal((html.match(/<article data-claim-id=/g)||[]).length, legacy.claims.length);
  for(const claim of legacy.claims) {
    assert.ok(html.includes(claim.claim_id));
    assert.ok(html.includes(resultBrowserItem(legacy,claim).badge));
  }
  assert.match(html,/추가 확인 필요 등급은 이전 버전에서 확인된 최소 수준/);
  assert.match(html,/선택하지 않은 쪽은 주장 추출 대상에서 제외/);
  assert.match(html,/원본 판정 기록/);
  assert.match(html,/브라우저 인쇄로 PDF 저장 가능/);
});

test('export escapes hostile names, quotes, citations and identifiers with no executable content', () => {
  const payload = '</pre><script>alert(1)</script><img src=x onerror=alert(1)>';
  const claim = structuredClone(legacy.claims[0]);
  claim.quote=payload; claim.claim_id='" onmouseover="alert(1)';
  for(const element of claim.provisional_grade?.elements ?? claim.elements) for(const ref of element.evidence_refs) ref.quote=payload;
  const html=resultReportHtml({...legacy,claims:[claim]}, {companyName:payload,reportName:payload});
  assert.doesNotMatch(html,/<script|<img|data-claim-id="" onmouseover/);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/default-src 'none'/);
  assert.match(html,/data-claim-id="&quot; onmouseover=&quot;alert\(1\)"/);
});

test('partial failure, empty claims and missing metadata remain explicit in UI and export', () => {
  const empty={...legacy,claims:[],hold_reasons:['UNRECOGNIZED_REASON'],pipeline:{status:'completed',extraction_outcome:{status:'partial',failed_sources:[{physical_page:1,source_id:'failed-source'}]}}};
  const html=resultReportHtml(empty);
  for(const text of ['부분 완료','전체 0건','failed-source','상세 사유는 제공되지 않았습니다','보고서 전체에 주장이 없다는 뜻은 아닙니다']) assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/분석 완료 ·|회사명 미제공|연도 미제공/);
  const ui=renderToStaticMarkup(React.createElement(ResultView,{result:empty}));
  assert.match(ui,/부분 완료/); assert.match(ui,/확정 조건을 충족한 주장은 0건입니다/);
  assert.doesNotMatch(ui,/<details open="" class="result-count-note"/);
});

test('one-line evidence uses verified present references and keeps held claims ungraded', () => {
  const provisional = legacy.claims.find(c=>resultBrowserItem(legacy,c).bucket==='provisional');
  assert.match(claimEvidenceLine(legacy,provisional),/^추가 확인 필요/);
  const hold = legacy.claims.find(c=>resultBrowserItem(legacy,c).bucket==='hold');
  assert.doesNotMatch(claimEvidenceLine(legacy,hold),/E[0-3]/);
  const altered = {...provisional,provisional_grade:{...provisional.provisional_grade,elements:[{element_id:'M1',state:'present',evidence_refs:[]}]}};
  assert.doesNotMatch(claimEvidenceLine(legacy,altered),/근거 확인$/);
});

test('source jumps distinguish the claim, evidence element and physical page for identical quotes', () => {
  const { selectedSourceRef } = require('./sourceSplitModel.ts');
  const refs=[{ref_id:'claim',kind:'claim',quote:'same text',physical_page:16},{ref_id:'m1',kind:'evidence',element_id:'M1',quote:'same text',physical_page:16},{ref_id:'m5',kind:'evidence',element_id:'M5',quote:'same text',physical_page:16},{ref_id:'m5-other',kind:'evidence',element_id:'M5',quote:'same text',physical_page:24}];
  assert.equal(selectedSourceRef(refs,{}).ref_id,'claim');
  assert.equal(selectedSourceRef(refs,{quote:'same text',page:16,elementId:'M5'}).ref_id,'m5');
  assert.equal(selectedSourceRef(refs,{quote:'same text',page:24,elementId:'M5'}).ref_id,'m5-other');
  assert.equal(selectedSourceRef(refs,{quote:'same text',page:25,elementId:'M5'}),undefined);
});


test('scope-confirmed export does not present superseded hold text as the current status', () => {
  const { claimHoldReasons } = require('./resultModel.ts');
  const confirmed = scoped.claims.find(claim => resultBrowserItem(scoped, claim).confirmed);
  const claim = { ...confirmed, hold_reason: 'EVIDENCE_INSUFFICIENT', provisional_grade: { display_type: 'hold', hold_reasons: ['과거 보류 사유'] } };
  const html = resultReportHtml({ ...scoped, claims: [claim] });
  assert.ok(resultBrowserItem(scoped, claim).confirmed);
  for (const reason of claimHoldReasons(claim)) assert.ok(!html.includes(`<p>${reason}</p>`));
  assert.match(html, /원본 판정 기록/);
  assert.match(html, /과거 보류 사유/);
});

test('document names prefer the uploaded filename and reject generated/placeholder metadata', () => {
  const { documentName, metadataText, reportTitle } = require('./documentName.ts');
  assert.equal(documentName({display_name:'보고서 57'}, 'LG화학 2025 지속가능경영보고서.PDF'),'LG화학 2025 지속가능경영보고서');
  assert.equal(documentName({original_filename:'LG전자 2025.pdf'}),'LG전자 2025');
  assert.equal(documentName({title:'2025 지속가능경영보고서'}),'2025 지속가능경영보고서');
  assert.equal(documentName({display_name:'카카오 2025.pdf'}),'카카오 2025');
  assert.equal(documentName({company_name:'LG화학'}),'LG화학');
  for(const value of ['미제공','회사명 미제공','unknown','없음','N/A']) assert.equal(metadataText(value),undefined);
  for(const value of ['보고서 · 119쪽','보고서 57','기존 보고서 22fc9c59','분석 보고서']) assert.equal(reportTitle(value),undefined);
  assert.equal(documentName({display_name:'보고서 57'}),undefined);
});

test('unknown optional headline metadata is omitted in screen and exported report', () => {
  const result={...legacy,pipeline:{status:'completed'},page_map:[]};
  const summary=renderToStaticMarkup(React.createElement(ResultReportSummary,{result,companyName:'unknown'}));
  assert.doesNotMatch(summary, /<dt>회사|<dt>보고연도|미제공|없음|unknown/);
  const screen=renderToStaticMarkup(React.createElement(ResultView,{result,reportName:'보고서 · 119쪽',companyName:'미제공'}));
  const heading=screen.match(/<header[^]*?<\/header>/)[0];
  assert.doesNotMatch(heading,/미제공|없음|unknown|119쪽/);
  const report=resultReportHtml(result,{companyName:'없음',reportName:'unknown'});
  assert.doesNotMatch(report.match(/<header[^]*?<\/dl>/)[0], /미제공|없음|unknown/);
});

test('124 confirmed / 0 provisional / 87 held fixture retains exact statuses with a confirmed-only chart', () => {
  const result=load('w21/confirmed-majority.result.json');
  const original=JSON.stringify(result), counts=resultBrowserSummary(result);
  assert.deepEqual([counts.confirmed,counts.provisional,counts.hold,counts.total],[124,0,87,211]);
  assert.deepEqual(counts.confirmedGrades,{E3:31,E2:31,E1:31,E0:31});
  const html=renderToStaticMarkup(React.createElement(ResultView,{result,reportName:'합성 검증 보고서.pdf',companyName:'검증 기업',pageCount:119}));
  assert.match(html,/>합성 검증 보고서<\/h2>/);
  assert.doesNotMatch(html,/class="provisional-key"|class="provisional" style|role="tab"[^>]*>잠정/);
  assert.match(html,/확정 124 \+ 보류 87 = 추출 주장 211건/);
  assert.doesNotMatch(html,/잠정/);
  for(const grade of ['E3','E2','E1','E0']) assert.ok(html.includes(`aria-label="${grade} 확정 31건"`));
  for(const c of result.claims.slice(124)) assert.equal(resultBrowserItem(result,c).grade,null);
  assert.equal(JSON.stringify(result),original);
});
