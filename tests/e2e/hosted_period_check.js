async page => {
  const calls = [];
  let scope = {
    revision: 1,
    reporting_scope: { report_year: 2024, period_start: '2024-01-01', period_end: '2024-12-31', origin: 'detected', warning: null },
    plan: {
      status: 'proposed', selected_claim_pages: [1], selected_evidence_pages: [1, 2],
      failure_reasons: [], unreadable_pages: [], unknown_pages: [], conflict_pages: [],
      pages: [{ page: 1, category: 'e_narrative', reasons: [], snippet: '' }],
      reporting_period_detection: {
        status: 'detected',
        candidates: [{ source_ref: { physical_page: 2, quote: '보고기간은 2024년 1월 1일부터 12월 31일까지입니다.' } }],
        exceptions: [{ source_ref: { physical_page: 2, quote: '일부 성과는 2025년 상반기를 포함합니다.' } }],
      },
    },
    selection: { pages: [1, 2], claim_pages: [1], selection_sha256: 'a'.repeat(64) },
  };
  const run = { run_id: 'fx7-browser-run', document_id: 'fx7-doc', status: 'partial_blocked', selected_pages: [1, 2], status_url: '/v1/runs/fx7-browser-run', error_code: 'LIVE_BINDING_UNAVAILABLE', result_url: '/v1/runs/fx7-browser-run/result' };
  await page.route('**/hosted-api/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname.replace('/hosted-api', '');
    let data;
    if (path === '/v1/runtime') data = { analysis_backend: 'hosted', accept_new_runs: true, accept_uploads: true, live_analysis: false, live_disabled: true, upload_notice: '무료 UI 시험', consent_version: 'test', pipeline_profile: 'finals-unattended-v2', limits: { max_upload_bytes: 10000000, selected_pages: 10, max_pdf_pages: 300, original_days: 7 } };
    else if (path === '/v1/session') data = { user_id: 'test', tenant_id: 'test', role: 'admin', csrf_token: 'fx7-csrf', expires_at: '2099-01-01' };
    else if (path === '/v1/documents') data = { document_id: 'fx7-doc', page_count: 3, size_bytes: 50, expires: 9999999999, sha256: 'c'.repeat(64) };
    else if (path.endsWith('/scope-plan/selection')) {
      const body = request.postDataJSON();
      if (request.headers()['if-match'] !== `"${scope.revision}"`) throw new Error('If-Match not pinned');
      calls.push(body);
      scope = { ...scope, revision: scope.revision + 1, reporting_scope: { ...scope.reporting_scope, ...body.reporting_scope, origin: 'manual', warning: null }, selection: { ...scope.selection, selection_sha256: String(scope.revision + 1).repeat(64) } };
      data = scope;
    } else if (path.endsWith('/scope-plan')) data = scope;
    else if (path === '/v1/runs') {
      if (request.postDataJSON().scope_selection_sha256 !== scope.selection.selection_sha256) throw new Error('run uses stale selection');
      data = run;
    } else if (path.endsWith('/result')) data = { schema: 'r108-hosted-result-v1', claims: [], reviews: [], hold_reasons: ['LIVE_BINDING_UNAVAILABLE'], page_map: [1, 2], pipeline: { status: 'partial_blocked', reporting_scope: { report_year: 2022, period_start: '2022-01-01', period_end: '2022-12-31', origin: 'operator_default', warning: '보고기간 추정 실패(기본값 사용)' } } };
    else throw new Error(`Unexpected hosted request: ${path}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('http://127.0.0.1:5197/analyze');
  await page.locator('input[type=file]').setInputFiles({ name: 'report.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nsynthetic UI fixture') });
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await page.getByLabel('보고연도', { exact: true }).waitFor();
  if (await page.getByLabel('보고연도', { exact: true }).inputValue() !== '2024') throw new Error('detected period missing');
  await page.getByText('보고기간 원문과 예외', { exact: true }).click();
  if (!await page.getByText(/예외 · 2쪽/).isVisible()) throw new Error('exception missing');
  await page.getByLabel('보고연도', { exact: true }).fill('2023');
  await page.getByLabel('보고기간 시작', { exact: true }).fill('2023-01-01');
  await page.getByLabel('보고기간 종료', { exact: true }).fill('2023-12-31');
  await page.getByRole('button', { name: '범위 수정 저장', exact: true }).click();
  await page.getByText(/사람이 수정한 기간/).waitFor();
  if (calls[0]?.reporting_scope?.report_year !== 2023) throw new Error('manual period not sent');
  await page.getByLabel('보고연도', { exact: true }).fill('2022');
  await page.getByLabel('보고기간 시작', { exact: true }).fill('2022-01-01');
  await page.getByLabel('보고기간 종료', { exact: true }).fill('2022-12-31');
  await page.getByRole('button', { name: /분석 시작/ }).click();
  await page.getByText('보고기간 추정 실패(기본값 사용)', { exact: true }).waitFor();
  if (calls[1]?.reporting_scope?.report_year !== 2022 || scope.revision !== 3) throw new Error('start did not save period');
  return { status: 'passed', manual_revision: scope.revision, period_writes: calls.map(c => c.reporting_scope), result_warning: 'visible', exception: 'visible', provider_calls: 0 };
}
