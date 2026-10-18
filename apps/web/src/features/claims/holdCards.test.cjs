const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const ts = require('typescript');
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (m, f) => m._compile(ts.transpileModule(fs.readFileSync(f, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, f);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { ProvisionalHold } = require('./ProvisionalHold.tsx');
const { MissingEvidenceCard } = require('./MissingEvidenceCard.tsx');
const html = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const ref = { source_id: 's', page_num: 2, quote: '2024년 94.7 천tCO2eq', verification_state: 'verified', char_start: 1, char_end: 22 };
const grade = { display_type: 'hold', hold_reasons: ['처리 실패: 응답 형식 확인 필요', '추정치 · 범주 미확정'], evidence_note: '미확인·위치 확인은 문서 전체의 근거 부재 판정이 아닙니다.', needed_evidence: [{ track: 'performance', target_grade: 'E1', elements: ['P1'] }] };
test('four sections preserve server causes and exact page quote', () => {
 const s = html(ProvisionalHold, { grade, sources: [{ ref, label: '주장 원문' }], pageLabel: () => '원본 PDF 106쪽', facts: ['서버가 확인한 원문 수치: 94.7'] });
 for (const text of ['확인된 사실', '정확한 원문', '미해결 원인', '다음 확인', ...grade.hold_reasons, grade.evidence_note, ref.quote, '원본 PDF 106쪽']) assert.ok(s.includes(text), text);
 assert.ok(s.indexOf('확인된 사실') < s.indexOf('정확한 원문') && s.indexOf('정확한 원문') < s.indexOf('미해결 원인'));
 assert.ok(s.indexOf('미해결 원인') < s.indexOf('다음 확인'));
});
test('missing fields are listed and unknown cause is not guessed', () => {
 const s = html(ProvisionalHold, { grade: { display_type: 'hold' } });
 for (const text of ['미제공 정보', '확인된 사실', '쪽·인용', '보류 원인', '다음 확인 항목']) assert.ok(s.includes(text));
 assert.doesNotMatch(s, /기업.*결손|원문에.*없습니다|추정치/);
});
test('unverified source remains candidate, not confirmed fact', () => {
 const s = html(MissingEvidenceCard, { sources: [{ ref: { ...ref, verification_state: 'candidate' }, label: '요소 후보' }] });
 assert.match(s, /미검증 후보/); assert.doesNotMatch(s, /원문 검증 완료/);
});
test('absence only described when engine and search agree', () => {
 const s = html(MissingEvidenceCard, { element: { element_id: 'P1', state: 'unknown' }, missing: { reason: '위치 확인 필요', search: { absence_admissible: false } } });
 assert.match(s, /위치 확인 필요/); assert.doesNotMatch(s, /원문에서 확인 안 됨/);
 const a = html(MissingEvidenceCard, { element: { element_id: 'P1', state: 'absent' }, missing: { search: { absence_admissible: true, scope_note: '106쪽 동일 표' } } });
 assert.match(a, /원문에서 확인 안 됨/); assert.match(a, /106쪽 동일 표/);
});
test('hold only, no grade manufactured', () => {
 assert.equal(html(ProvisionalHold, { grade: { display_type: 'grade' } }), '');
 assert.doesNotMatch(html(ProvisionalHold, { grade }), /E0~E3|확정 등급.*E/);
});

test('unmapped candidate cannot offer a working source jump', () => {
 const s = html(MissingEvidenceCard, { sources: [{ ref, label: '요소 후보', openable: false }], onSourceOpen() {} });
 assert.match(s, /button[^>]*disabled/); assert.match(s, /원문 이동 위치 미확인/);
});
