import assert from 'node:assert/strict';
import test from 'node:test';
import {category, pickPages, tocAnchors} from './sectionHeuristics.ts';

test('an unrelated TOC number cannot define an environmental section', () => {
  assert.deepEqual(tocAnchors('Contents Environmental information Social 89', 120), [{page:89,section:'S'}]);
  assert.deepEqual(tocAnchors('Contents Environmental 20 Social 50 Governance 80', 120), [
    {page:20,section:'E'}, {page:50,section:'S'}, {page:80,section:'G'},
  ]);
});
test('strong environmental content overrides incidental governance headings', () => {
  assert.equal(category('이사회 기후 탄소 온실가스 에너지 감축 재생에너지').section, 'E');
  assert.equal(category('목표 목표 목표 목표').section, 'O');
});
test('the 60-page cap preserves environmental pages before assurance appendices', () => {
  const pages=Array.from({length:70},(_,i)=>({page:i+1,section:i<60?'E':'A',assurance:i>=60,score:i<60?2:50,source:'키워드'}));
  const result=pickPages(pages,['E','A']);
  assert.deepEqual(result.pages,Array.from({length:60},(_,i)=>i+1));
  assert.equal(result.dropped,10);
  assert.equal(pickPages(pages,['A']).pages.length,10);
});
