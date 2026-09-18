# Local comparison workspace evidence

Date: 2026-09-09 KST

## Scope

- Added `ComparisonWorkspace` over the fixed run, document, version, comparison-create, and comparison-get APIs.
- Reused `ComparisonPage`, React native selects/buttons, and `requestJson`/`errorMessage`; added no dependency.
- Did not edit root-owned routing/composition or the concurrently owned `ComparisonPage`.

## Browser TDD

The runnable browser check was written first and loaded through Vite at
`http://127.0.0.1:4218/` in Orca page `9cae5436-43ca-4413-bdb3-5ee108d815b4`.
The RED run failed at the intended boundary:

```text
Failed to resolve import "/src/features/comparison/ComparisonWorkspace.tsx"
Does the file exist?
```

After coordinator review clarified the two gates, the updated browser check also failed RED
while the role branch still exposed `YEAR_COMPARISON_DISABLED`; it timed out waiting for the
required permission message. The minimal follow-up maps role denial and the backend environment
error separately without rendering a raw error code.

A final privacy mutation changed only `csrfToken` while a comparison GET was held. It failed RED
because the request was not aborted, then passed after the shared tenant/run/session scope guard
included token rotation.

The final GREEN run returned:

```json
{"bounded_pagination":true,"completed_candidate":true,"controlled_http_boundary":true,"csrf":true,"environment_disabled":true,"fixed_comparison_get":true,"late_create_ignored":true,"late_get_ignored":true,"late_load_ignored":true,"lazy_versions":true,"missing_artifact_truthful":true,"prior_year_ready_only":true,"repeated_cursor_guard":true,"role_gate":true,"same_company":true,"session_cleared":true,"stable_idempotency":true}
```

The final browser console contained no warning/error messages (only Vite connection/HMR debug
and React development info). `tests/e2e/comparison_workspace_check.mjs`
explicitly marks its controlled `window.fetch` responses as test doubles: it renders the real
React components over HTTP but does not represent a backend integration test.

## Verification

```text
node --check tests/e2e/comparison_workspace_check.mjs
exit 0

pnpm --dir apps/web typecheck
exit 0

pnpm --dir apps/web build
exit 0; Vite 6.4.3 transformed 52 modules

uv run --no-sync pytest tests/acceptance/test_comparison.py tests/integration/test_comparison_api.py -q --tb=short
exit 0; 16 passed, 2 upstream deprecation warnings

git diff --no-index --check /dev/null <each newly owned file>
exit 1 for each expected untracked-file diff; no whitespace-error output
```

## Boundaries and not run

- The catalog walker stops on a repeated cursor and at 10,000 items. Versions are loaded only
  after explicit document selection, then filtered to `ready` and `currentYear - 1`.
- Comparison POST retries keep one 16–128-character idempotency key for an unchanged body,
  send CSRF, and follow only `/v1/comparisons/{resource_id}` with bounded polling.
- Run/tenant changes abort and ignore catalog, create, and comparison GET work; document changes
  abort prior version work; session invalidation clears private state before notifying the root.
- Actual same-origin mounted route and persisted missing-prior browser flow are root-owned and
  were not run here. Live AWS/model calls, customer data, GitHub, and cloud changes were not run.
- The web package currently has no lint or standalone unit-test script; these were not claimed.

## Coordinator actual HTTP acceptance

After worker release, the coordinator accepted the final workspace with the root-owned
App route, API composition and optional prior-version browser fixture. The final normal
`pnpm --dir apps/web build` passed (52 modules), and `node --check
tests/e2e/comparison_http_check.mjs` exited 0.

The coordinator executed `checkComparisonHttp()` from that script through `orca eval`
against the built app at `http://[::1]:4217`, using the same-origin harness with
`--include-prior-version` and `ENABLE_YEAR_COMPARISON=true`. It forwarded every request to
the actual HTTP API without substituting responses. The final rebuilt page returned:

```json
{"actual_receipt":true,"document_selected":true,"missing_artifact_not_run":true,"prior_version_selected":true,"route_mounted":true}
```

The result also included the actual persisted comparison ID. A real ready prior document
without a published approved artifact produced POST 202 followed by
`not_run/prior_comparison_artifact_missing` and zero changes; the browser displayed its
reason. This verifies the local absence path, while the separate backend acceptance tests
cover approved candidate comparison. It makes no claim about live model or AWS execution.
