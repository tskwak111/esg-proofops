// Local Vite component regression. Pass API-shaped evidence from the real PDF fixture.
export async function check(elements) {
  const resource = performance.getEntriesByType('resource').find(r => /\/\.vite\/deps\/react\.js/.test(r.name));
  const { default: React } = await import(resource.name);
  const { default: { createRoot } } = await import(resource.name.replace('react.js', 'react-dom_client.js'));
  const { MissingEvidenceCard } = await import('/src/features/claims/MissingEvidenceCard.tsx');
  const host = document.createElement('main');
  document.getElementById('root').replaceChildren(host);
  createRoot(host).render(React.createElement(MissingEvidenceCard, { elements, onSourceOpen() {} }));
  for (let i = 0; i < 100 && !host.querySelector('[data-testid="missing-evidence-card"]'); i++)
    await new Promise(resolve => setTimeout(resolve, 50));
  const card = host.querySelector('[data-testid="missing-evidence-card"]');
  if (!card) throw new Error('Missing evidence card did not render');
  const text = card.textContent;
  for (const expected of ['이미지 쪽 1개 미확인', '텍스트 판독불가 쪽: 없음',
    '이미지 내용 미확인 쪽: 1 (1개)', '전체 내용 판독 미완결 쪽: 1', '검색한 쪽: 1 / 전체 1쪽'])
    if (!text.includes(expected)) throw new Error(`Missing coverage: ${expected}`);
  if (text.includes('보고서에서 찾지 못함')) throw new Error('Unreviewed image treated as report absence');
  if (card.querySelectorAll('[data-evidence-status="undetermined"]').length !== elements.length)
    throw new Error('Unreviewed content must stay undetermined');
  return { elements: elements.length, unresolvedImagePages: [1], unreadableTextPages: [], text };
}
