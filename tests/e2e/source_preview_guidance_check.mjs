// Run through playwright-cli in the task Vite browser. No provider calls.
export async function check() {
  const resource = performance.getEntriesByType('resource').map(entry => entry.name)
    .find(name => /\/react\.js\?v=/.test(name));
  const version = resource ? new URL(resource).search : '';
  const { default: React } = await import(/* @vite-ignore */ '/node_modules/.vite/deps/react.js' + version);
  const { default: { createRoot } } = await import(/* @vite-ignore */ '/node_modules/.vite/deps/react-dom_client.js' + version);
  const { SourceViewer } = await import('/src/components/SourceViewer.tsx');
  const { ExportWorkspace } = await import('/src/features/reports/ExportWorkspace.tsx');
  const originalFetch = window.fetch;
  const host = document.createElement('div');
  document.body.append(host);
  let root = createRoot(host);
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const flush = () => new Promise(resolve => setTimeout(resolve, 40));
  const waitFor = async predicate => {
    for (let i = 0; i < 50; i += 1) {
      if (predicate()) return;
      await flush();
    }
    throw new Error('Timed out: ' + host.textContent);
  };
  const ref = { source_id: '55555555-5555-4555-8555-555555555555',
    document_version_id: '66666666-6666-4666-8666-666666666666',
    parse_manifest_id: '77777777-7777-4777-8777-777777777777', page_num: 48,
    printed_page_label: '47', raw_text_sha256: 'a'.repeat(64),
    char_start: 12, char_end: 44, quote: '<img src=x onerror=alert(1)> RE100',
    bbox: null, location_quality: 'unlocated', verification_state: 'verified' };
  let selected = ref;
  let previewCalls = 0;
  window.fetch = async (url, init = {}) => {
    const target = new URL(String(url), location.origin);
    if (target.pathname.endsWith('/view')) {
      assert(init.method === 'POST', 'Source tickets remain authenticated POSTs');
      assert(new Headers(init.headers).get('X-CSRF-Token') === 'csrf-test', 'Source ticket retains CSRF');
      return Response.json({ url: '/preview.png?ticket=fixture', expires_at: '', sha256: 'a'.repeat(64) });
    }
    if (target.pathname === '/preview.png') {
      previewCalls += 1;
      assert(target.searchParams.get('char_start') === String(selected.char_start), 'Preview must identify the selected stored span start');
      assert(target.searchParams.get('char_end') === String(selected.char_end), 'Preview must identify the selected stored span end');
      return new Response(new Blob(['png'], { type: 'image/png' }), { headers: {
        'X-Page-Width-Pt': '600', 'X-Page-Height-Pt': '800', 'X-Source-Highlight': 'allowed' } });
    }
    if (target.pathname.endsWith('/exports')) return Response.json({ error: {
      code: 'EXPORT_SIZE_LIMIT', message: 'Export request could not be completed.' } }, { status: 409 });
    throw new Error('Unexpected fetch: ' + target.pathname);
  };
  try {
    for (const value of [ref, { ...ref, bbox: [72, 60, 300, 100], location_quality: 'located', verification_state: 'candidate' }]) {
      selected = value;
      root.render(React.createElement(SourceViewer, { csrfToken: 'csrf-test', runId: 'run', sources: [value], onSessionInvalid() {} }));
      await flush();
      [...host.querySelectorAll('button')].find(b => b.textContent.includes('원문 위치 열기')).click();
      await waitFor(() => host.querySelector('section[aria-label="선택한 원문 위치"]'));
      const preview = host.querySelector('section[aria-label="선택한 원문 위치"]');
      const quote = preview.querySelector('blockquote mark');
      assert(quote?.textContent === value.quote, 'Preview must visibly emphasize the exact selected quote');
      assert(!quote.closest('details'), 'Quote guidance must be visible without opening a disclosure');
      assert(preview.textContent.includes('PDF 48쪽') && preview.textContent.includes('인쇄 쪽 표시: 47'), 'Physical and printed page labels remain distinct');
      assert(!preview.querySelector('[data-source-highlight]'), 'Missing bbox and candidate refs must never get an overlay');
      assert(!preview.querySelector('img[src="x"]'), 'Quote markup must remain escaped text');
      root.unmount(); root = createRoot(host);
    }
    root.render(React.createElement(ExportWorkspace, { csrfToken: 'csrf-test', tenantKey: 'tenant', runId: 'run', onSessionInvalid() {} }));
    await flush();
    [...host.querySelectorAll('button')].find(b => b.textContent.includes('내보내기 생성')).click();
    await waitFor(() => host.querySelector('[role="alert"]'));
    const message = host.querySelector('[role="alert"]').textContent;
    assert(message.includes('32 MiB') && message.includes('1,000'), 'Export error must explain the existing byte and claim limits');
    assert(message.includes('쪽수') && message.includes('검토 근거'), 'Two pages can exceed the evidence snapshot limit');
    assert(message.includes('형식 변경') && message.includes('관리자'), 'Do not imply format changes or repeated retries reduce the snapshot');
    assert(!host.querySelector('a[download]'), 'Rejected exports must never gain a download');
    return { passed: true, previewCalls, visible_quote_guidance: true, no_invented_coordinates: true, export_limit_guidance: true };
  } finally {
    root.unmount(); host.remove(); window.fetch = originalFetch;
  }
}
