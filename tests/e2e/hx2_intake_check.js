// Offline browser proof: manual scope declaration and server failure detail.
async page => {
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.unroute('**/hosted-api/**');
  let edit;
  let scope = { revision: 1, reporting_scope: { report_year: 2024, period_start: '2024-01-01', period_end: '2024-12-31', origin: 'detected' },
    plan: { status: 'candidate_only', selected_claim_pages: [2], selected_evidence_pages: [2,3], failure_reasons: [], unreadable_pages: [], unknown_pages: [1], conflict_pages: [],
      pages: [{ page: 1, category: 'unknown', reasons: [] }, { page: 2, category: 'e_narrative', reasons: [] }, { page: 3, category: 'gri', reasons: [] }] },
    selection: { pages: [2,3], claim_pages: [2], selection_sha256: 'a'.repeat(64) } };
  const detail = 'HX2 서버 상세: 원문 처리 실패로 판정을 보류했습니다. 운영자 확인이 필요합니다.';
  const run = { run_id: 'hx2-fixture', document_id: 'hx2-fixture', status: 'partial_blocked', selected_pages: [1,2,3], status_url: '/v1/runs/hx2-fixture', result_url: '/v1/runs/hx2-fixture/result', error_code: 'FUTURE_PARSER_FAILURE' };
  await page.route('**/hosted-api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/hosted-api', '');
    let data;
    if (path === '/v1/runtime') data = { analysis_backend: 'hosted', accept_new_runs: true, accept_uploads: true, live_analysis: true, live_disabled: false, upload_notice: 'HX2 무료 검사', consent_version: 'hx2', pipeline_profile: 'finals-unattended-v2', limits: { max_upload_bytes: 150*1048576, selected_pages: 10, max_pdf_pages: 300, original_days: 7 } };
    else if (path === '/v1/session') data = { user_id: 'hx2', tenant_id: 'hx2', role: 'admin', csrf_token: 'offline-csrf', expires_at: '2099-01-01' };
    else if (path === '/v1/documents') data = { document_id: 'hx2-fixture', page_count: 3, size_bytes: 40, expires: 9999999999, sha256: 'c'.repeat(64) };
    else if (path.endsWith('/scope-plan/selection')) {
      edit = route.request().postDataJSON();
      check(edit.manual_selection === true, 'manual scope flag missing');
      check(route.request().headers()['if-match'] === '"1"', 'scope revision fence missing');
      scope = { ...scope, revision: 2, plan: { ...scope.plan, selected_claim_pages: edit.selected_claim_pages, selected_evidence_pages: edit.selected_evidence_pages }, selection: { pages: edit.selected_evidence_pages, claim_pages: edit.selected_claim_pages, selection_sha256: 'b'.repeat(64), manual_selection: true } };
      data = scope;
    } else if (path.endsWith('/scope-plan')) data = scope;
    else if (path === '/v1/runs' || path === '/v1/runs/hx2-fixture') data = run;
    else if (path.endsWith('/result')) data = { schema: 'r108-hosted-result-v1', claims: [], reviews: [], page_map: [1,2,3], hold_reasons: ['FUTURE_PARSER_FAILURE'], hold_reason_details: [{ code: 'FUTURE_PARSER_FAILURE', message: detail }], pipeline: { status: 'partial_blocked', reason: 'FUTURE_PARSER_FAILURE' }, confirmed_grade: null };
    else throw new Error(`unexpected ${path}`);
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('http://127.0.0.1:5198/analyze');
  await page.getByLabel('업로드 제한', { exact: true }).waitFor();
  await page.locator('input[type=file]').setInputFiles({ name: 'hx2.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nHX2 browser fixture') });
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await page.getByLabel('주장 쪽 번호', { exact: true }).fill('1,2');
  await page.getByLabel('근거 검색 쪽 번호', { exact: true }).fill('1,2,3');
  await page.getByRole('button', { name: '분석 시작', exact: true }).click();
  await page.getByTestId('hosted-result').waitFor();
  const text = await page.getByTestId('hosted-result').innerText();
  check(edit.manual_selection, 'edit was not submitted');
  check(scope.plan.unknown_pages.includes(1), 'unknown page quality was erased');
  check(text.includes(detail), 'server-provided failure wording missing');
  check(!text.includes('상세 문구를 확인할 수 없습니다'), 'generic missing-detail fallback');
  check(text.includes('근거 없음으로 판정한 결과가 아닙니다'), 'empty parser failure became absent evidence');
  check(errors.length === 0, errors.join(','));
  return { manual_scope: true, revision_fence: true, unknown_preserved: true, server_failure_detail: true, real_provider_calls: 0 };
}
