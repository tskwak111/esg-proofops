// playwright-cli run-code --filename=tests/e2e/hosted_intake_check.js
// Built hosted Vite preview on 5197. All hosted traffic is intercepted; paid calls zero.
async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const docs = new Map(); const runs = new Map(); const polls = new Map();
  let logins = 0; let nextError = null;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const scopeFor = id => {
    const year = 2020 + Number(id.split('-').at(-1));
    return {
      revision: 1,
      reporting_scope: { report_year: year, period_start: `${year}-01-01`, period_end: `${year}-12-31`, origin: 'detected' },
      plan: { status: 'proposed', selected_claim_pages: [1], selected_evidence_pages: [1, 2],
        failure_reasons: [], pages: [{ page: 1, category: 'e_narrative', reasons: [] }],
        unreadable_pages: [], unknown_pages: [], conflict_pages: [] },
      selection: { pages: [1, 2], claim_pages: [1], selection_sha256: id.padEnd(64, 'a') },
    };
  };
  const result = { schema: 'r108-hosted-result-v1', claims: [], reviews: [], hold_reasons: [], page_map: [1, 2], pipeline: { status: 'completed' } };
  await page.route('**/hosted-api/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname.replace('/hosted-api', '');
    let data; let status = 200;
    if (path === '/v1/runtime') data = { analysis_backend: 'hosted', accept_new_runs: true, accept_uploads: true, live_analysis: true, live_disabled: false, upload_notice: 'PI1 무료 브라우저 모의 시험', consent_version: 'test', pipeline_profile: 'finals-unattended-v2', limits: { max_upload_bytes: 150 * 1048576, selected_pages: 10, max_pdf_pages: 300, original_days: 7, user_active_runs: 5, daily_runs: 10 } };
    else if (path === '/v1/session' && !logins) { status = 401; data = { error: { code: 'AUTH_REQUIRED' } }; }
    else if (path === '/v1/auth/invitation') {
      logins++;
      data = { user_id: 'same-user', tenant_id: 'same-tenant', role: 'admin', csrf_token: 'pi1-test-csrf', expires_at: '2099-01-01' };
    } else if (path === '/v1/documents') {
      check(request.headers()['x-csrf-token'] === 'pi1-test-csrf', 'upload missing session CSRF');
      const id = `doc-${docs.size + 1}`;
      data = { document_id: id, page_count: 3, size_bytes: 50, expires: 9999999999, sha256: 'c'.repeat(64) };
      docs.set(id, data);
    } else if (path.endsWith('/cancel')) {
      const id = path.split('/')[3]; const run = runs.get(id); data = { ...run, status: 'cancelled' }; runs.set(id, data);
    } else if (path.endsWith('/deletion-requests')) data = { deletion_id: 'pi1-delete', status: 'completed' };
    else if (path.endsWith('/scope-plan')) data = scopeFor(path.split('/')[3]);
    else if (path === '/v1/runs') {
      const body = request.postDataJSON();
      check(request.headers()['x-csrf-token'] === 'pi1-test-csrf', 'start missing session CSRF');
      check(body.scope_selection_sha256 === scopeFor(body.document_id).selection.selection_sha256, 'cross-document scope mixed');
      if (nextError) { status = 429; data = { error: { code: nextError } }; nextError = null; }
      else {
        const id = `run-${runs.size + 1}`;
        data = { run_id: id, document_id: body.document_id, status: runs.size === 0 ? 'running' : 'queued', selected_pages: [1, 2], status_url: `/v1/runs/${id}`, stage: runs.size === 0 ? 'extract' : 'queued', progress: .3, queue_position: runs.size || null };
        runs.set(id, data);
      }
    } else if (path.endsWith('/result')) data = result;
    else if (/^\/v1\/runs\/run-\d+$/.test(path)) {
      const id = path.split('/').at(-1); polls.set(id, (polls.get(id) ?? 0) + 1); data = runs.get(id);
    } else throw new Error(`Unexpected hosted request: ${request.method()} ${path}`);
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('http://127.0.0.1:5197/analyze');
  await page.getByLabel('초대 코드', { exact: true }).fill('pi1-synthetic-invitation-0123456789');
  await page.getByRole('button', { name: '초대 코드로 입장' }).click();
  const file = index => ({ name: `report-${index}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nsynthetic browser fixture') });
  const card = index => page.getByTestId('document-analysis').filter({ has: page.getByRole('heading', { name: `report-${index}.pdf`, exact: true }) });
  await page.locator('input[type=file]').setInputFiles(file(1));
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await card(1).getByRole('button', { name: '분석 시작', exact: true }).click();
  await card(1).getByTestId('document-status').filter({ hasText: '주장 추출' }).waitFor();
  check(await page.locator('input[type=file]').isEnabled(), 'running analysis disabled upload input');
  await page.locator('input[type=file]').setInputFiles([2, 3, 4, 5].map(file));
  check(await page.getByRole('button', { name: '업로드', exact: true }).isEnabled(), 'running analysis disabled upload');
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  for (let i = 2; i <= 5; i++) {
    await card(i).getByRole('button', { name: '분석 시작', exact: true }).click();
    check(await card(i).getByLabel('보고연도', { exact: true }).inputValue() === String(2020 + i), `period mixed for doc ${i}`);
    await card(i).getByTestId('document-status').filter({ hasText: `대기 ${i - 1}번째` }).waitFor();
  }
  check(logins === 1 && runs.size === 5 && docs.size === 5, 'one invitation did not accept five reports');
  check(await page.getByTestId('document-analysis').count() === 5, 'earlier document state disappeared');
  for (let i = 1; i <= 5; i++) {
    const run = runs.get(`run-${i}`);
    runs.set(run.run_id, { ...run, status: 'completed', stage: 'result', progress: 1, queue_position: null, result_url: `${run.status_url}/result` });
    await card(i).getByTestId('document-status').filter({ hasText: '완료' }).waitFor({ timeout: 15000 });
    await card(i).getByText('선택한 범위의 분석이 정상 완료되었으나 환경 주장을 발견하지 못했습니다. 보고서 전체에 주장이 없다는 뜻은 아닙니다.', { exact: true }).waitFor();
  }
  check(await page.getByText('이 서버가 결과 상세를 아직 제공하지 않아 화면에 표시할 수 없습니다.', { exact: true }).count() === 0, 'loaded result shown as unavailable');
  await page.locator('input[type=file]').setInputFiles(file(6));
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  for (const [code, text] of [['QUEUE_FULL', '대기열'], ['DAILY_RUN_LIMIT', '횟수 한도'], ['BUDGET_EXCEEDED', '비용을 예약할 수 없습니다']]) {
    nextError = code;
    await card(6).getByRole('button', { name: '분석 시작', exact: true }).click();
    await card(6).getByRole('alert').filter({ hasText: code }).waitFor();
    check((await card(6).getByRole('alert').textContent()).includes(text), `unexplained admission ${code}`);
    check(await card(6).getByRole('button', { name: '분석 시작', exact: true }).isEnabled(), 'failed admission locked retry');
  }
  await card(6).getByRole('button', { name: '분석 시작', exact: true }).click();
  await card(6).getByTestId('document-status').filter({ hasText: '대기' }).waitFor();
  const held = runs.get('run-6');
  runs.set('run-6', { ...held, status: 'accounting_pending', error_code: 'PROVIDER_CREDIT_EXHAUSTED', provider_error_code: 'PROVIDER_CREDIT_EXHAUSTED' });
  await card(6).getByText('오류 코드: PROVIDER_CREDIT_EXHAUSTED', { exact: true }).waitFor({ timeout: 15000 });
  check((await card(6).textContent()).includes('충전 확인'), 'provider cause not explained');
  const terminalPolls = polls.get('run-6');
  await page.waitForTimeout(1600);
  check(polls.get('run-6') === terminalPolls, 'accounting pending kept polling');
  await page.locator('input[type=file]').setInputFiles(file(7));
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await card(7).getByText('분석 접수 가능', { exact: true }).waitFor();
  check(await card(7).getByRole('button', { name: '분석 시작', exact: true }).isEnabled(), 'another document error blocked new document');
  await card(7).getByRole('button', { name: '분석 시작', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles(file(8));
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await card(8).getByRole('button', { name: '분석 시작', exact: true }).click();
  await card(7).getByRole('button', { name: '분석 취소', exact: true }).click();
  await card(7).getByTestId('document-status').filter({ hasText: '취소됨' }).waitFor();
  const eighth = runs.get('run-8'); runs.set('run-8', { ...eighth, status: 'running', stage: 'tag' });
  await card(8).getByTestId('document-status').filter({ hasText: '요소 태깅' }).waitFor({ timeout: 15000 });
  page.once('dialog', dialog => dialog.accept());
  await card(7).getByRole('button', { name: '업로드한 PDF 삭제', exact: true }).click();
  await card(7).waitFor({ state: 'detached' });
  check(await card(8).isVisible(), 'one document deletion removed another');
  await page.setViewportSize({ width: 390, height: 844 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile overflow');
  check(errors.length === 0, `browser errors: ${errors.join('; ')}`);
  const outcome = { status: 'passed', invitations: logins, five_acceptances: 5, initial_running: 1, initial_queued: 4, completed: 5, multi_file_upload: true, independent_periods_results: true, admission_errors: ['QUEUE_FULL', 'DAILY_RUN_LIMIT', 'BUDGET_EXCEEDED'], provider_cause_visible: true, accounting_pending_poll_stopped: true, other_document_start_enabled: true, document_cancel_delete_isolated: true, mobile_width: 390, provider_calls: 0 };
  await page.evaluate(value => { window.pi1BrowserOutcome = value; }, outcome);
  return outcome;
}
