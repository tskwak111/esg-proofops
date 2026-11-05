#!/usr/bin/env bash
# Local offline web checks. No API server or provider credentials are needed.
# Usage: scripts/test_web.sh [all|node|claims|hosted]
# Requires installed workspace dependencies, Node with type stripping, playwright-cli + Chrome.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null || { echo 'test_web: node is required' >&2; exit 1; }
command -v playwright-cli >/dev/null || { echo 'test_web: playwright-cli is required; install the local tool before running this script' >&2; exit 1; }
exec node --input-type=module - "${1:-all}" <<'JS'
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const mode = process.argv[2];
if (!['all', 'node', 'claims', 'hosted'].includes(mode)) {
  throw new Error('Usage: scripts/test_web.sh [all|node|claims|hosted]');
}
const root = process.cwd();
const web = join(root, 'apps/web');
const scratch = await mkdtemp(join(tmpdir(), 'proofops-web-'));
const session = `web-${process.pid}`;
const vite = join(web, 'node_modules/vite/bin/vite.js');
const children = new Set();
let browserOpen = false;
let closing;

function start(command, args, options = {}) {
  const child = spawn(command, args, { cwd: command === 'playwright-cli' ? scratch : root, ...options, stdio: ['ignore', 'pipe', 'pipe'] });
  children.add(child);
  child.once('close', () => children.delete(child));
  return child;
}
async function run(command, args, options) {
  const child = start(command, args, options);
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', resolve);
  });
  process.stdout.write(output);
  if (code !== 0) throw new Error(`${command} failed (${code})`);
  return output;
}
async function stop(child) {
  if (!children.has(child)) return;
  const closed = new Promise(resolve => child.once('close', resolve));
  child.kill('SIGTERM');
  const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
  await closed;
  clearTimeout(timer);
}
function cleanup() {
  return closing ??= (async () => {
    if (browserOpen) {
      await closeBrowser().catch(error => { console.error(error.message); process.exitCode = 1; });
    }
    await Promise.all([...children].map(stop));
    await rm(scratch, { recursive: true, force: true });
  })();
}
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  process.once(signal, async () => { await cleanup(); process.exit(code); });
}
const env = { ...process.env, VITE_DEMO_STATIC: 'false', VITE_ANALYSIS_BACKEND: 'legacy', API_PUBLIC_BASE_URL: 'http://127.0.0.1:1' };
async function server(args, port) {
  const child = start(process.execPath, [vite, ...args, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: web, env });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  let failure;
  child.once('error', error => { failure = error; });
  for (let i = 0; i < 200; i++) {
    if (failure || child.exitCode !== null) throw new Error(`Vite failed: ${failure ?? output}`);
    // Wait for this process to bind, so an occupied port cannot pass readiness.
    if (output.includes('Local:')) {
      const response = await fetch(`http://127.0.0.1:${port}`, { signal: AbortSignal.timeout(1000) }).catch(() => null);
      if (response?.ok) return child;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Vite readiness timed out: ${output}`);
}
async function runCode(code) {
  const file = join(scratch, 'check.js');
  await writeFile(file, code);
  return run('playwright-cli', [`-s=${session}`, 'run-code', `--filename=${file}`]);
}
async function cliCheck(code) {
  const output = await runCode(code);
  // Some CLI versions print tool errors but exit 0. Require successful completion.
  if (!/"web_check_passed":\s*true/.test(output) || output.includes('### Error')) {
    throw new Error('Browser check did not report success');
  }
}
async function openBrowser(port) {
  browserOpen = true;
  await run('playwright-cli', [`-s=${session}`, 'open']);
  await cliCheck(`async page => {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://127.0.0.1:${port}' || /^\\/(hosted-api|v1|auth|local)\\//.test(url.pathname)) return route.abort();
      return route.continue();
    });
    await page.goto('http://127.0.0.1:${port}');
    return { web_check_passed: true };
  }`);
}
async function closeBrowser() {
  const output = await run('playwright-cli', [`-s=${session}`, 'close']);
  if (output.includes('### Error')) throw new Error('Browser session did not close');
  browserOpen = false;
}
try {
  if (mode === 'all' || mode === 'node') {
    await run(process.execPath, ['--experimental-strip-types', 'tests/e2e/element_labels_check.mjs']);
  }
  if (mode === 'all' || mode === 'claims') {
    const dev = await server([], 5173);
    await openBrowser(5173);
    for (const name of ['claim_workspace', 're_review', 'review_queue_gap', 'candidate_source_view', 'preliminary_classification', 'source_preview_guidance']) {
      console.log(`CHECK ${name}`);
      const moduleUrl = `/@fs${resolve(root, 'tests/e2e', `${name}_check.mjs`)}`;
      await cliCheck(`async page => {
        const result = await page.evaluate(async url => (await import(url)).check(), ${JSON.stringify(moduleUrl)});
        return { web_check_passed: true, result };
      }`);
    }
    await closeBrowser();
    await stop(dev);
  }
  if (mode === 'all' || mode === 'hosted') {
    const outDir = join(scratch, 'hosted-dist');
    await run(process.execPath, [vite, 'build', '--outDir', outDir], { cwd: web, env: { ...env, VITE_ANALYSIS_BACKEND: 'hosted', VITE_DEMO_STATIC: 'true' } });
    const preview = await server(['preview', '--outDir', outDir], 5197);
    await openBrowser(5197);
    console.log('CHECK hosted_intake');
    const callback = await readFile(join(root, 'tests/e2e/hosted_intake_check.js'), 'utf8');
    await runCode(`async page => {
      const check = (\n${callback}\n);
      const result = await check(page);
      return { web_check_passed: true, result };
    }`);
    // The CLI returns early on native dialogs, even when the callback accepts
    // them. The fixture publishes this outcome only after its final assertions.
    await cliCheck(`async page => {
      await page.waitForFunction(() => window.pi1BrowserOutcome?.status === 'passed', null, { timeout: 30000 });
      const result = await page.evaluate(() => window.pi1BrowserOutcome);
      return { web_check_passed: true, result };
    }`);
    await closeBrowser();
    await stop(preview);
  }
  console.log(`PASS test_web (${mode})`);
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await cleanup();
}
JS
