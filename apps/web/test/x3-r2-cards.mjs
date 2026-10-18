// Read-only audit of supplied R2 draft cases, not a human accuracy evaluation.
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('usage: node test/x3-r2-cards.mjs cases.json audit.json');
const cases = JSON.parse(readFileSync(input, 'utf8')).cases;
const server = await createServer({ server:{middlewareMode:true},appType:'custom',optimizeDeps:{noDiscovery:true,include:[]},logLevel:'error',envDir:false });
try {
 const { ResultView } = await server.ssrLoadModule('/src/features/hosted/HostedResult.tsx');
 const records = [];
 for (const c of cases.filter(c=>c.provisional_grade?.display_type==='hold')) {
   const claim = {claim_id:c.claim_id,page_num:c.source_refs[0].page_num,original_page_num:c.physical_page,quote:c.atomic_quote,track:c.track,source_refs:c.source_refs,source_quality:c.source_status.status,elements:[],decision:null,revision:1,missing_evidence:[],provisional_grade:c.provisional_grade,hold_reason:null,possible_grade_range:null,confirmed_grade:null};
   const result = {schema:'r108-hosted-result-v1',claims:[claim],reviews:[],hold_reasons:[],page_map:Array(claim.page_num-1).fill(null).concat(c.physical_page)};
   const markup=renderToStaticMarkup(createElement(ResultView,{result}));
   for(const heading of ['확인된 사실','정확한 원문 (쪽·인용)','미해결 원인','다음 확인']) assert.ok(markup.includes(heading),`${c.case_id} missing ${heading}`);
   for(const reason of c.provisional_grade.hold_reasons) assert.ok(markup.includes(reason), `${c.case_id} lost cause ${reason}`);
   assert.ok(markup.includes(c.provisional_grade.evidence_note),`${c.case_id} lost note`);
   assert.ok(markup.includes(`p.${c.physical_page}`), `${c.case_id} lost original page`);
   assert.ok(markup.includes('범주 판단 근거·확정 여부'),`${c.case_id} missing unavailable details`);
   assert.doesNotMatch(markup,/확정 등급 E[0-3]|원문에서 확인 안 됨/);
   records.push({case_id:c.case_id,classification:c.hold_classification,status:'passed',domain_guard:'no invented absence/category/grade',limitation:'R2 raw processing codes, independent cause adjudication and potential category fields are not available in public projection'});
 }
 assert.equal(records.length,27);
 assert.equal(records.filter(r=>r.classification==='파이프라인 문제').length,9);
 assert.equal(records.filter(r=>r.classification==='정당한 보류').length,18);
 writeFileSync(output,JSON.stringify({status:'passed',holds:27,pipeline:9,conservative:18,records,not_run:['human semantic accuracy','live hosted server','missing server-cause restoration']},null,2)+'\n');
 console.log('R2 cards: 27 holds, 9 pipeline and 18 conservative; source/notes preserved; no absence invented');
} finally { await server.close(); }
