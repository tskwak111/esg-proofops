const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, filename);
const { HostedApiError, createHostedClient, describeError } = require('./hostedClient.ts');

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
