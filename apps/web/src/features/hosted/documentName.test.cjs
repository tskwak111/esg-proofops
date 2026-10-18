const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const ts = require('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const { cleanReportName, reportTitle, documentName, reportNames } = require('./documentName.ts');
const cases = [
  ['LGChem_Sustainability_Report_2025_KOR', 'LGChem 2025 지속가능경영보고서'],
  ['Kakao_SustainabilityReport2025_KR', 'Kakao 2025 지속가능경영보고서'],
  ['Samsung_Electronics_Sustainability_Report_2025_KOR', 'Samsung Electronics 2025 지속가능경영보고서'],
  ['2025_SK하이닉스_지속가능경영보고서', '2025 SK하이닉스 지속가능경영보고서'],
  ['hmc-sr-kor-2025', 'hmc-sr-kor-2025'],
  ['NAVER_2025_통합보고서', 'NAVER 2025 통합보고서'],
  ['2024-2025_LGE_Sustainability_Report_Korean', 'LGE 2024-2025 지속가능경영보고서'],
  ['2025-POSCO_Holdings_Report_KOR', '2025-POSCO Holdings Report'],
  ['KT 2025 지속가능경영보고서', 'KT 2025 지속가능경영보고서'],
  ['SK_Telecom_Sustainability_Report_2025F', 'SK Telecom 2025 지속가능경영보고서'],
  ['Samsung_SDI_Sustainability_Report_2025_KR_fn', 'Samsung SDI 2025 지속가능경영보고서'],
  ['2025_기아_지속가능경영보고서', '2025 기아 지속가능경영보고서'],
];
for (const [input, expected] of cases) test(`real report filename: ${input}`, () => {
  for (const filename of [input, `${input}.pdf`, `/reports/${input}.PDF`, `C:\\reports\\${input}.pdf`]) {
    assert.equal(reportTitle(filename), expected);
    assert.equal(cleanReportName(filename), expected);
    assert.equal(documentName({ original_filename: filename }), expected);
  }
  assert.equal(reportTitle(expected), expected, 'normalization is idempotent');
});

test('all specified year suffixes and repeated file markers are removed without eating meaningful titles', () => {
  for (const suffix of ['F', 'fn', 'final', 'Final', 'KOR', 'KR', 'kor', 'Korean', 'ENG', 'EN', '(KOR)', '_K', '_KR_fn']) {
    assert.equal(reportTitle(`Acme_Sustainability_Report_2025${suffix}.pdf`), 'Acme 2025 지속가능경영보고서', suffix);
  }
  assert.equal(reportTitle('  2025_기아_지속가능경영보고서  .pdf '), '2025 기아 지속가능경영보고서');
  assert.equal(reportTitle('KR_2025_통합보고서'), 'KR 2025 통합보고서');
  assert.equal(reportTitle('Acme 2025 Finance'), 'Acme 2025 Finance');
  assert.equal(reportTitle('Acme 2025 final results'), 'Acme 2025 final results');
  for (const value of [undefined, null, 42, '', '/reports/분석_보고서.pdf', 'unknown.pdf']) assert.equal(reportTitle(value), undefined);
});

test('PDF title metadata is normalized; meaningful Korean titles win while the uploader filename stays intact', async () => {
  const { PDFDocument } = require('pdf-lib');
  const { ux1CompanyName } = require('./ux1Metadata.ts');
  assert.equal(ux1CompanyName({ filename: '2024-2025_LGE_Sustainability_Report_Korean.pdf' }), 'LGE');
  const { uploadMetadata } = require('./ux1Metadata.ts');
  for (const [title, expected] of [
    ['SK_Telecom_Sustainability_Report_2025F', 'SK Telecom 2025 지속가능경영보고서'],
    ['2024-2025 LGE Sustainability Report Korean', 'LGE 2024-2025 지속가능경영보고서'],
    ['2025_기아_지속가능경영보고서', '2025 기아 지속가능경영보고서'],
  ]) {
    const pdf = await PDFDocument.create(); pdf.addPage(); pdf.setTitle(title);
    const bytes = await pdf.save();
    assert.deepEqual(await uploadMetadata(new Blob([bytes])), { original_filename: undefined, title: expected });
    assert.equal(documentName({ ux1_metadata: { title } }), expected);
    const file = new File([bytes], 'NAVER_2025_통합보고서.pdf');
    const metadata = await uploadMetadata(file);
    assert.equal(metadata.original_filename, file.name);
    assert.equal(documentName({ ux1_metadata: metadata }), expected);
  }
});

const titleCases = [
  ['LGChem_Sustainability_Report_2025_KOR', 'LG화학 지속가능경영보고서 2025', 'LG화학 지속가능경영보고서 2025'],
  ['Samsung_Electronics_Sustainability_Report_2025_KOR', '삼성전자 2025년 지속가능경영보고서', '삼성전자 2025년 지속가능경영보고서'],
  ['SK_Telecom_Sustainability_Report_2025F', 'SK Telecom 2025 지속가능경영보고서', 'Microsoft Word - x.docx'],
  ['2025_기아_지속가능경영보고서', '2025 기아 지속가능경영보고서', 'Untitled'],
];

test('meaningful Korean PDF titles win across metadata locations; English and generic titles defer to filenames', () => {
  for (const [filename, expected, title] of titleCases) {
    for (const doc of [{ ux1_metadata: { title } }, { title }]) {
      assert.equal(documentName({ ...doc, original_filename: filename + '.pdf' }), expected);
      assert.equal(documentName(doc, filename + '.pdf'), expected);
    }
  }
  const filename = 'SK_Telecom_Sustainability_Report_2025F.pdf';
  for (const title of ['Acme Sustainability Report 2025', 'Different metadata title', '분석 보고서', '보고서 57', '지속가능경영보고서', '2025 지속가능경영보고서', '내부 제목', '제목 없음', 'Microsoft Word - 보고서.docx', '/한글/Untitled.pdf']) {
    assert.equal(documentName({ ux1_metadata: { title }, original_filename: filename }), 'SK Telecom 2025 지속가능경영보고서', title);
  }
  assert.equal(documentName({ ux1_metadata: { title: 'Untitled' }, title: titleCases[0][2], original_filename: filename }), titleCases[0][1]);
  assert.equal(documentName({ ux1_metadata: { title: titleCases[0][2] }, title: titleCases[1][2], original_filename: filename }), titleCases[0][1]);
});

test('example, result, history, comparison and both PDF titles use the same source and display name', async () => {
  const React = require('react');
  const { renderToStaticMarkup: render } = require('react-dom/server');
  const { loadExamples } = require('./exampleCatalog.ts');
  const { ResultView } = require('./HostedResult.tsx');
  const { ComparisonResults } = require('./UX1Comparison.tsx');
  const { resultReportHtml } = require('./ResultReport.tsx');
  const result = JSON.parse(fs.readFileSync(`${__dirname}/../../../test/fixtures/w21/confirmed-majority.result.json`));
  for (const [filename, expected, title] of [...cases, ...titleCases]) {
    const doc = { document_id: 'named', sha256: 'same', ux1_metadata: { original_filename: `${filename}.pdf`, title: title ?? 'Different metadata title' } };
    const before = JSON.stringify(doc);
    const run = { run_id: 'run', document_id: 'named', status: 'completed', created_at: '2026-10-18', result_url: '/result' };
    const client = { listDocuments: async () => ({ items: [doc], next_cursor: null }), listRuns: async () => ({ items: [run], next_cursor: null }), getResult: async () => result };
    const examples = await loadExamples(client, new AbortController().signal);
    const name = documentName(doc);
    assert.equal(examples[0].name, expected);
    assert.equal(reportNames([doc, { document_id: 'legacy', sha256: 'same' }]).legacy, expected);
    assert.ok(render(React.createElement(ResultView, { result, reportName: title ? name : `${filename}.pdf` })).includes(`data-testid="result-heading">${expected}</h2>`));
    assert.ok(render(React.createElement(ComparisonResults, { reports: [{ result, name, runId: 'run', pageCount: 119, pages: [1] }] })).includes(`<h4>${expected}</h4>`));
    for (const reportMode of ['summary', 'full']) {
      const html = resultReportHtml(result, { reportName: title ? name : `${filename}.pdf`, reportMode });
      assert.ok(html.includes(`<h1>${expected}</h1>`));
      assert.ok(html.includes(`<title>ProofOps · ${expected}`));
    }
    assert.equal(JSON.stringify(doc), before);
  }
});

const companyCases = [
  [{ filename: '2025_기아_지속가능경영보고서' }, '기아'],
  [{ filename: '2025_SK하이닉스_지속가능경영보고서' }, 'SK하이닉스'],
  [{ filename: 'NAVER_2025_통합보고서' }, 'NAVER'],
  [{ filename: 'KT 2025 지속가능경영보고서' }, 'KT'],
  [{ title: '삼성전자 2025년 지속가능경영보고서', filename: 'Different_Report_2025.pdf' }, '삼성전자'],
  [{ ux1_metadata: { title: 'LG화학 지속가능경영보고서 2025' }, filename: 'Different_Report_2025.pdf' }, 'LG화학'],
  [{ filename: 'SK_Telecom_Sustainability_Report_2025F' }, 'SK Telecom'],
  [{ filename: 'Samsung_SDI_Sustainability_Report_2025_KR_fn' }, 'Samsung SDI'],
  [{ filename: 'Kakao_SustainabilityReport2025_KR' }, 'Kakao'],
  [{ filename: '2024-2025_LGE_Sustainability_Report_Korean' }, 'LGE'],
  [{ filename: '2025-POSCO_Holdings_Report_KOR' }, 'POSCO Holdings'],
  [{ filename: 'hmc-sr-kor-2025' }, undefined],
];
for (const [doc, expected] of companyCases) test(`company from shared report name: ${doc.filename}`, () => {
  const { ux1CompanyName } = require('./ux1Metadata.ts');
  const before = JSON.stringify(doc);
  assert.equal(ux1CompanyName(doc), expected);
  assert.equal(JSON.stringify(doc), before);
});

test('company extraction strips only standalone edge years and does not infer names from codes or other data', () => {
  const { ux1CompanyName } = require('./ux1Metadata.ts');
  for (const title of ['2024-2025_기아_기업시민보고서', '2025년_기아_2024-2025_Report', '기아_2025년_통합보고서']) assert.equal(ux1CompanyName({ title }), '기아');
  assert.equal(ux1CompanyName({ filename: 'Company2025_Report.pdf' }), 'Company2025');
  assert.equal(ux1CompanyName({ filename: '2025_3M_Report.pdf' }), '3M');
  assert.equal(ux1CompanyName({ filename: '2025_기아_지속가능경영보고서.pdf', title: 'Untitled' }), '기아');
  for (const filename of ['2025_Report', '2024-2025_통합보고서', '2025년_기업시민보고서', '2025_SR_KOR_Report', '2025_12345_Report', 'hmc-sr-kor-2025']) {
    assert.equal(ux1CompanyName({ filename, author: '추측회사', claims: [{ quote: '추측회사' }] }), undefined, filename);
  }
  assert.equal(ux1CompanyName({ author: '추측회사', claims: [{ quote: '추측회사' }] }), undefined);
  assert.equal(ux1CompanyName({ company_name: '공식 회사', title: '삼성전자 2025년 지속가능경영보고서' }), '공식 회사');
});

test('Kia company summary and PDF expose the company without a year and omit unidentifiable codes', () => {
  const React = require('react');
  const { renderToStaticMarkup: render } = require('react-dom/server');
  const { ux1CompanyName } = require('./ux1Metadata.ts');
  const { ResultReportSummary, resultReportHtml } = require('./ResultReport.tsx');
  const result = JSON.parse(fs.readFileSync(`${__dirname}/../../../test/fixtures/w21/confirmed-majority.result.json`));
  const companyName = ux1CompanyName({ filename: '2025_기아_지속가능경영보고서.pdf' });
  const summary = render(React.createElement(ResultReportSummary, { result, companyName }));
  assert.ok(summary.includes('<dt>회사</dt><dd>기아</dd>'));
  assert.ok(resultReportHtml(result, { companyName }).includes('<dt>회사</dt><dd>기아</dd>'));
  assert.ok(!render(React.createElement(ResultReportSummary, { result, companyName: ux1CompanyName({ filename: 'hmc-sr-kor-2025' }) })).includes('<dt>회사</dt>'));
});
