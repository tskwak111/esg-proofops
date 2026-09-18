# Local export workspace evidence

Date: 2026-09-09 (Asia/Seoul)

## Scope

- Added the standalone `ExportWorkspace` browser controls for the frozen `export_create`, `export_get`, and `export_download` contracts.
- Kept route composition and `ReportPreview` integration out of this worker-owned change.
- Used only existing React and `requestJson`/`isSessionError` helpers; no dependency was added.

## TDD browser check

The browser test was added first. Its first Orca-controlled Vite run failed because `/src/features/reports/ExportWorkspace.tsx` did not exist, which was the expected RED condition.

The final test ran in Orca's embedded browser against Vite over HTTP at `http://127.0.0.1:4206/` (4204 was already occupied by an unrelated repository process and was not touched):

```text
orca eval ... export_workspace_check.mjs?v=6
ok: true
partial_default_false=true
idempotency_retry=true
idempotency_body_reset=true
polling_terminal=true
ready_download_only=true
trusted_download_origin=true
reissue_once=true
known_url_refresh=true
tenant_cleared=true
session_cleared=true
```

The check exercises real React rendering with controlled HTTP responses. It verifies CSRF placement, idempotency-key reuse/replacement, queued/building/ready polling, the absence of download controls before ready, rejection of an untrusted download origin, one explicit expired-link reissue, URL-known export refresh without a list endpoint, and stale tenant/session clearing. Orca browser console inspection returned no messages.

## Build verification

```text
pnpm --dir apps/web typecheck
exit 0

pnpm --dir apps/web build
exit 0; Vite built 49 modules
```

## Not run / integration boundary

- Actual backend export persistence, snapshot construction, and signed-download behavior were not run because TASK-031 backend integration is owned separately and is not yet composed here.
- `/runs/:runId/report` route mounting is root-owned and was intentionally not changed.
- No live AWS, model, GitHub, customer, or private-data call was made.
- The web package currently defines no standalone lint or unit-test script; the scoped TypeScript check, production build, and Orca HTTP browser check are the available verification for this change.

## Coordinator integration verification

The worker boundaries above describe its initial delivery. The coordinator subsequently mounted
`ExportWorkspace` at `/runs/:runId/report`, added the report navigation link, and verified the
composed application. A delayed known-export GET across a tenant change first failed the browser
check (`Late known-export GET must not restore prior tenant data`). One abort guard at the shared
`trackUntilTerminal` entry fixed the cause; the refreshed controlled React browser check passed
all eleven flags, including `known_tenant_cleared`.

Actual same-origin testing initially returned `409 EXPORT_INTEGRITY_FAILED`: the test harness
replaced the parser/claims but left dependent export/summary/analysis/rescore services bound to
the old parser. The harness now constructs every dependent service from the same explicitly
synthetic fixture stores. Production source verification was not changed.

On 2026-09-09 KST, the built application served at `http://[::1]:4217` with a fresh temporary
SQLite database passed `tests/e2e/export_http_check.mjs` in Orca's browser. This check clicks the
actual mounted form and download controls; it does not mock HTTP responses. Results:

```text
route_mounted=true finalization_gate=true partial_ready=true
private_download=true sha256_verified=true csrf_denied=true
downloaded bytes=92985
ZIP SHA256=de9f6b0d6d4d60c4e1aa8e34dee190e9f1f2823667708885e8786cd35942d230
```

The unfinished report gives an actionable Korean message, partial output reaches persisted
`ready`, and the real attachment bytes match the authorized hash. Download responses use
`no-store`; missing CSRF blocks ticket issuance. An additional actual API request generated
JSON/CSV/HTML together. API acceptance tests separately inspect ZIP/report contents and races.

```text
VITE_LOCAL_SYNTHETIC=true pnpm --dir apps/web build
exit 0; TypeScript and Vite build, 50 modules

uv run --no-sync pytest tests/acceptance/test_exports.py tests/integration/test_local_api_composition.py -q --tb=short
exit 0; 15 passed, 2 upstream deprecation warnings

uv run --no-sync ruff check tests/e2e/local_browser_server.py packages/proofops/application/exports.py packages/proofops/adapters/local/export_store.py apps/api/src/proofops_api/routers/exports.py apps/api/src/proofops_api/composition.py apps/api/src/proofops_api/main.py tests/integration/test_local_api_composition.py tests/acceptance/test_exports.py
exit 0
```

Real AWS/model/customer and approved domain/retention gates remain not_run. The fixture approval
labels apply only to this generated local synthetic test data.
