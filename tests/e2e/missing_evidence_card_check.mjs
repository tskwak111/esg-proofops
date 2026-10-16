// UI fixture only: copied Kakao checkpoint + free local search, all unconfirmed.
export async function check() {
  const resource = performance.getEntriesByType('resource').find(r => /\/\.vite\/deps\/react\.js/.test(r.name));
  const { default: React } = await import(resource.name);
  const { default: { createRoot } } = await import(resource.name.replace('react.js', 'react-dom_client.js'));
  const routerResource = performance.getEntriesByType('resource').find(r => /\/\.vite\/deps\/react-router\.js/.test(r.name));
  const { MemoryRouter } = await import(routerResource.name);
  const { ClaimWorkspace } = await import('/src/features/claims/ClaimWorkspace.tsx');
  const fixture = await (await fetch('/@fs/path/to/ESG_ProofOps/.local/r108-sprint1/.local/r108-mc2-ui-fixture.json')).json();
  const nativeFetch = window.fetch;
  window.fetch = async (url, init) => String(url).includes(`/claims/${fixture.detail.claim.claim_id}`)
    ? Response.json(fixture.detail) : nativeFetch(url, init);
  const host = document.createElement('main');
  document.getElementById('root').replaceChildren(host);
  const note = document.createElement('p');
  note.textContent = '카카오 사본 · UI 검증용 · 기존 API 재생 보류, native 후보만 표시';
  host.before(note);
  createRoot(host).render(React.createElement(MemoryRouter, {}, React.createElement(ClaimWorkspace, {
    runId: fixture.run_id, claimId: fixture.detail.claim.claim_id, csrfToken: 'ui-fixture',
    tenantKey: fixture.tenant_id, session: { user_id: 'ui-fixture', tenant_id: fixture.tenant_id,
      role: 'viewer', csrf_token: 'ui-fixture', expires_at: '2027-01-01T00:00:00Z' },
    onSessionInvalid() {}, onDataChanged() {},
  })));
  for (let i = 0; i < 100; i++) {
    if (host.querySelector('[data-testid="missing-evidence-card"]')) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const card = host.querySelector('[data-testid="missing-evidence-card"]');
  if (!card || card.querySelectorAll('[data-evidence-status="undetermined"]').length !== 8)
    throw new Error('Expected eight conservative Kakao goal-element cards');
  if (!card.querySelector('[data-undetermined-reason]')) throw new Error('MC2 subreason missing');
  if (!card.textContent.includes('판독불가') || !card.textContent.includes('정밀 검증 필요'))
    throw new Error('Missing coverage/outside-selection note');
  const hasPreview = card.textContent.includes('미검증 인용 미리보기');
  if (!hasPreview) throw new Error('MC2 must show an unverified native quote preview');
  card.querySelector('details').open = true;
  card.scrollIntoView();
  return { cardVisible: true, elements: 8, confirmed: 0, fixtureOnly: true,
    subreasons: [...card.querySelectorAll('[data-undetermined-reason]')].map(e => e.dataset.undeterminedReason),
    previewVisible: hasPreview,
    runId: fixture.run_id, claimId: fixture.detail.claim.claim_id };
}
