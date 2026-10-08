// Component regression, run through the Vite browser with playwright-cli.
export async function check() {
  const resource = performance.getEntriesByType('resource').map(e => e.name)
    .find(name => /\/react\.js\?v=/.test(name));
  const version = resource ? new URL(resource).search : '';
  const { default: React } = await import(/* @vite-ignore */ '/node_modules/.vite/deps/react.js' + version);
  const { default: { createRoot } } = await import(/* @vite-ignore */ '/node_modules/.vite/deps/react-dom_client.js' + version);
  const { App } = await import('/src/App.tsx');
  const originalFetch = window.fetch;
  const originalPath = location.pathname;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const flush = () => new Promise(resolve => setTimeout(resolve, 40));
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const waitFor = async predicate => {
    for (let i = 0; i < 50; i++) { if (predicate()) return; await flush(); }
    throw new Error('Upload/analysis state did not settle: ' + host.textContent);
  };
  const ready = { version_id: '11111111-1111-4111-8111-111111111111', status: 'ready', page_count: 207 };
  const option = id => ({ id, name: id, status: 'approved', reason: null });
  let runBody, readyRead = false;
  window.fetch = async (url, init = {}) => {
    const path = new URL(String(url), location.origin).pathname;
    if (path === '/v1/session') return Response.json({ user_id: 'operator', tenant_id: 'tenant-a', role: 'admin', csrf_token: 'test-only' });
    if (path === '/local/submission') return Response.json({ worker_enabled: true, candidate_rule_pack_id: 'candidate-a', selected_pages: [66, 67] });
    if (path === '/v1/companies') return Response.json({ items: [{ company_id: 'company-a', legal_name: 'SK이노베이션' }], next_cursor: null });
    if (path === '/v1/runtime-options') return Response.json({ rights_profiles: [option('rights-a')], consent_profiles: [option('consent-a')], runtime_bindings: [option('runtime-a')], rule_packs: [], enabled_modes: ['disclosure'] });
    if (path === '/v1/documents') return Response.json({ document_id: 'document-a' }, { status: 201 });
    if (path === '/v1/documents/document-a/versions') return Response.json({ version_id: ready.version_id, upload_id: '22222222-2222-4222-8222-222222222222', post_url: '/local/uploads/22222222-2222-4222-8222-222222222222/content', post_fields: {} }, { status: 201 });
    if (path === '/local/uploads/22222222-2222-4222-8222-222222222222/content') return new Response(null, { status: 204 });
    if (path === '/v1/uploads/22222222-2222-4222-8222-222222222222/complete') return Response.json({ status_url: '/v1/versions/11111111-1111-4111-8111-111111111111' }, { status: 202 });
    if (path === '/v1/versions/11111111-1111-4111-8111-111111111111') { readyRead = true; return Response.json(ready); }
    if (path === '/v1/preflight') return Response.json({ ready: true, checks: [] });
    if (path === '/v1/runs' && init.method === 'POST') {
      runBody = JSON.parse(init.body);
      return Response.json({ run_id: 'run-a', status: 'queued', current_stage: 'parse', revision: 1, coverage: {} }, { status: 202 });
    }
    return Response.json({ error: { code: 'TEST_READ_UNAVAILABLE', message: path } }, { status: 404 });
  };
  const set = async (id, value) => {
    const el = host.querySelector('#' + id);
    const prototype = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
    await flush();
  };
  try {
    history.pushState({}, '', '/documents/new');
    root.render(React.createElement(App));
    await waitFor(() => host.querySelector('#company option[value="company-a"]'));
    for (const [id, value] of [['company', 'company-a'], ['rights-profile', 'rights-a'], ['consent-profile', 'consent-a'], ['runtime-binding', 'runtime-a'], ['document-title', 'SK이노베이션 통합보고서 2024'], ['report-year', '2024'], ['period-start', '2024-01-01'], ['period-end', '2024-12-31']]) await set(id, value);
    const input = host.querySelector('#pdf-file');
    const files = new DataTransfer();
    files.items.add(new File(['%PDF-test-only'], 'KOR_SKI_2024.pdf', { type: 'application/pdf' }));
    input.files = files.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await flush();
    host.querySelector('form[aria-label="PDF 문서 등록"] button').click();
    await waitFor(() => readyRead);
    await flush(); await flush();
    assert(host.querySelector('#document-title').value === 'SK이노베이션 통합보고서 2024', 'Ready upload must retain the title after parent rerender');
    assert(host.querySelector('#period-start').value === '2024-01-01', 'Ready upload must retain reporting dates');
    assert(host.textContent.includes('207페이지'), 'Ready document version must stay visible');
    await waitFor(() => host.querySelector('#selected-pages') && !host.querySelector('form[aria-label="문서 분석 실행"] button').disabled);
    await set('selected-pages', '66,67');
    host.querySelector('form[aria-label="문서 분석 실행"] button').click();
    await waitFor(() => runBody);
    assert(runBody.document_version_id === ready.version_id, 'Analysis POST must use the ready version');
    assert(JSON.stringify(runBody.selected_pages) === '[66,67]', 'Analysis POST must use the selected physical pages');
    return { ready_form_retained: true, analysis_post: true, selected_pages: runBody.selected_pages };
  } finally {
    root.unmount(); host.remove(); window.fetch = originalFetch;
    history.pushState({}, '', originalPath);
  }
}
