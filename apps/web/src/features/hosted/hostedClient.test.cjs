const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, filename);
const { HostedApiError, createHostedClient, describeError } = require('./hostedClient.ts');
const { runOutcome } = require('./hostedClient.ts');

test('manual scope edits declare the manual selection and preserve revision fencing', async () => {
  let sent;
  const client = createHostedClient({ fetchImpl: async (url, init) => {
    sent = init;
    return new Response(JSON.stringify({ revision: 2 }));
  } });
  await client.editScope('sk-fixture', { revision: 1 }, [3, 11], [3, 11, 135]);
  assert.equal(JSON.parse(sent.body).manual_selection, true);
  assert.deepEqual(JSON.parse(sent.body).selected_claim_pages, [3, 11]);
  assert.equal(sent.headers['If-Match'], '"1"');
});

test('unknown failure codes retain server-provided detail', () => {
  const { holdReasonText } = require('./hostedClient.ts');
  const detail = '원문을 처리하지 못했습니다. 운영자 확인이 필요합니다.';
  assert.equal(holdReasonText('FUTURE_PARSER_FAILURE', [{ code: 'FUTURE_PARSER_FAILURE', message: detail }]), detail);
  assert.match(holdReasonText('PARSER_FAILED'), /파싱.*운영자/);
});

test('H5 native reader and page render limits expose concrete reasons without evidence absence', () => {
  for (const [code, cause] of [
    ['PARSER_NATIVE_TEXT_UNREADABLE', /보조 텍스트 파서/],
    ['SOURCE_ATTESTATION_RENDER_LIMIT', /이미지 크기.*한도/],
  ]) {
    const failed = runOutcome({ status: 'failed', error_code: code });
    assert.match(failed.reasons.join(' '), cause);
    assert.match(failed.reasons.join(' '), /판정하지 않았습니다/);
    assert.doesNotMatch(failed.reasons.join(' '), /근거 없음/);
  }
});

test('parser memory and corrupt table failures remain explicit and never claim evidence absence', () => {
  for (const code of ['PARSER_JAVA_HEAP_EXHAUSTED', 'W9_GRID_TEXT_MISMATCH', 'PARSER_FAILED']) {
    const failed = runOutcome({ status: 'failed', error_code: code });
    assert.equal(failed.kind, 'failed');
    assert.match(failed.reasons.join(' '), /파싱|표 원문/);
    assert.match(failed.reasons.join(' '), /판정하지 않았습니다/);
    assert.doesNotMatch(failed.reasons.join(' '), /근거 없음|완료/);
  }
});

test('maintenance and expired worker lease remain explicit without retrying uncertain work', () => {
  assert.match(describeError(new HostedApiError(503, 'MAINTENANCE', 60, '/v1/runs')), /서버 점검.*진행 중 분석.*점검 후/);
  const held = runOutcome({ status: 'accounting_pending', error_code: 'LEASE_EXPIRED' });
  assert.equal(held.kind, 'blocked');
  assert.match(held.reasons.join(' '), /서버 재시작.*비용 정산.*자동 재실행하지/);
  const failed = runOutcome({ status: 'failed', error_code: 'LEASE_EXPIRED_NO_DISPATCH' });
  assert.match(failed.reasons.join(' '), /모델 전송이 없어.*예약이 해제/);
});

test('intake refusal preserves documents and gives a useful next step', () => {
  const error = code => describeError(new HostedApiError(429, code, null, '/v1/runs'));
  assert.match(error('QUEUE_FULL'), /대기열.*업로드한 문서는 유지/);
  assert.match(error('DAILY_RUN_LIMIT'), /횟수 한도.*내일/);
  assert.doesNotMatch(error('DAILY_RUN_LIMIT'), /잠시 후/);
  assert.match(error('BUDGET_EXCEEDED'), /운영자.*이번 분석은 접수되지 않았습니다/);
  assert.doesNotMatch(error('BUDGET_EXCEEDED'), /잠시 후/);
});
test('provider authentication and availability errors ask for the correct operator action', () => {
  const error = code => describeError(new HostedApiError(503, code, null, '/v1/runs'));
  assert.match(error('PROVIDER_CREDIT_EXHAUSTED'), /크레딧.*충전/);
  assert.match(error('PROVIDER_AUTH_FAILED'), /인증.*키 확인/);
  assert.match(error('PROVIDER_ACCESS_DENIED'), /권한.*운영자/);
  assert.match(error('PROVIDER_RATE_LIMITED'), /요청 한도.*운영자/);
  assert.match(error('PROVIDER_UNAVAILABLE'), /서버 오류.*운영자/);
});
test('one accounting-pending run stops while another run continues polling', async () => {
  const counts = { held: 0, healthy: 0 };
  const run = (id, status) => ({ run_id: id, document_id: id, status, selected_pages: [1], status_url: `/v1/runs/${id}` });
  const client = createHostedClient({ sleep: async () => {}, fetchImpl: async url => {
    const id = String(url).split('/').at(-1); counts[id]++;
    return new Response(JSON.stringify(run(id, id === 'held' ? 'accounting_pending' : counts[id] === 1 ? 'running' : 'completed')));
  } });
  const updates = { held: [], healthy: [] };
  const done = await Promise.all(['held', 'healthy'].map(id => client.pollRun(run(id, 'queued'), next => updates[id].push(next.status))));
  assert.deepEqual(done.map(r => r.status), ['accounting_pending', 'completed']);
  assert.deepEqual(counts, { held: 1, healthy: 2 });
  assert.deepEqual(updates.healthy, ['queued', 'running', 'completed']);
});
