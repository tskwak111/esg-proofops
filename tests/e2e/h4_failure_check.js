// playwright-cli -s=h4 run-code --filename=tests/e2e/h4_failure_check.js
// Hosted preview on 5198. All API traffic is intercepted; no paid dispatch.
async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const codes = ['PARSER_FAILED', 'PARSER_MEMORY_LIMIT', 'PARSER_PDF_INVALID',
    'CLAIM_PAGES_UNREADABLE', 'SOURCE_ATTESTATION_UNAVAILABLE',
    'SOURCE_ATTESTATION_REPLAY_MISMATCH', 'EXTRACTION_INPUT_INVALID', 'PROBE_REQUEST_TOO_LARGE'];
  let documents = 0;
  let uploadError = null;
  const result = code => ({ schema: 'r108-hosted-result-v1', page_map: [5, 6], reviews: [],
    hold_reasons: [code], pipeline: { status: 'partial_blocked', reason: code,
      extraction_outcome: { status: 'partial', code: 'CLAIM_PAGE_PARSE_FAILURE',
        selected_claim_pages: [1, 2], parsed_claim_blocks: 1, processed_blocks: 1,
        page_failures: [{ physical_page: 2, code }] } },
    claims: [{ claim_id: 'h4-browser-fixture', quote: '브라우저 검사: 기존 처리된 주장',
      page_num: 1, bbox: null, track: 'performance', source_quality: 'unverified',
      source_refs: [], elements: [], hold_reason: code, possible_grade_range: null,
      confirmed_grade: null, decision: null, missing_evidence: [] }] });
  const run = id => ({ run_id: id, document_id: id, status: 'partial_blocked',
    selected_pages: [5, 6], status_url: `/v1/runs/${id}`, error_code: codes[Number(id)-1],
    result_url: `/v1/runs/${id}/result` });
  await page.route('**/hosted-api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/hosted-api', '');
    let data; let status = 200;
    if (path === '/v1/runtime') data = { analysis_backend: 'hosted', accept_new_runs: true,
      accept_uploads: true, live_analysis: true, live_disabled: false, upload_notice: 'H4 무료 브라우저 검사',
      consent_version: 'h4', pipeline_profile: 'finals-unattended-v2', limits: {
        max_upload_bytes: 150*1048576, selected_pages: 10, max_pdf_pages: 300, original_days: 7 } };
    else if (path === '/v1/session') data = { user_id: 'h4-fixture', tenant_id: 'h4-fixture',
      role: 'admin', csrf_token: 'h4-fixture-csrf', expires_at: '2099-01-01' };
    else if (path === '/v1/documents') {
      if (uploadError) { status = 422; data = { error: { code: uploadError } }; }
      else { documents++; data = { document_id: String(documents), page_count: 6,
        size_bytes: 50, expires: 9999999999, sha256: 'c'.repeat(64) }; }
    } else if (path.endsWith('/scope-plan')) data = { revision: 1,
      reporting_scope: { report_year: 2024, period_start: '2024-01-01', period_end: '2024-12-31', origin: 'detected' },
      plan: { status: 'proposed', selected_claim_pages: [5], selected_evidence_pages: [6],
        failure_reasons: [], pages: [{ page: 5, category: 'e_narrative', reasons: [] }],
        unreadable_pages: [], unknown_pages: [], conflict_pages: [] },
      selection: { pages: [5,6], claim_pages: [5], selection_sha256: 'a'.repeat(64) } };
    else if (path === '/v1/runs') data = run(route.request().postDataJSON().document_id);
    else if (path.endsWith('/result')) data = result(codes[Number(path.split('/')[3])-1]);
    else if (/^\/v1\/runs\/\d+$/.test(path)) data = run(path.split('/')[3]);
    else throw new Error(`Unexpected H4 request: ${path}`);
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('http://127.0.0.1:5198/analyze');
  await page.getByLabel('업로드 제한', { exact: true }).waitFor();
  check((await page.getByLabel('업로드 제한').innerText()).includes('150MiB'), 'runtime upload cap not shown');
  const file = name => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nH4 synthetic browser fixture') });
  for (let index=0; index<codes.length; index++) {
    const name = `h4-${index+1}.pdf`;
    await page.locator('input[type=file]').setInputFiles(file(name));
    await page.getByRole('button', { name: '업로드', exact: true }).click();
    const card = page.getByTestId('document-analysis').filter({ has: page.getByRole('heading', { name, exact: true }) });
    await card.getByRole('button', { name: '분석 시작', exact: true }).click();
    await card.getByTestId('hosted-result').waitFor();
    const text = await card.innerText();
    check(text.includes('브라우저 검사: 기존 처리된 주장'), 'partial claim lost');
    check(text.includes('읽지 못한 쪽') && text.includes('6쪽'), 'failed original page not mapped');
    check(!text.includes(`보류 사유 코드: ${codes[index]}`), `missing Korean explanation ${codes[index]}`);
    check(text.includes('근거 부재로 판정하지 않았습니다'), 'unreadable mistaken for absent');
  }
  uploadError = 'PDF_PASSWORD_REQUIRED';
  await page.locator('input[type=file]').setInputFiles(file('encrypted.pdf'));
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '열기 암호' }).waitFor();
  check(errors.length === 0, `browser errors: ${errors.join(',')}`);
  return { passed: codes, encrypted_guidance: true, server_cap_mib: 150,
    partial_claim_preserved: true, page_mapping: true, paid_calls: 0 };
}
