# TASK-023 — 다년도 비교 / FR-023 / AT-023

Date: 2026-09-09 (Asia/Seoul)

## Implemented scope

- Added a deterministic application service that compares approved current/prior target
  snapshots and returns only `modified`, `new`, `removed_candidate`, or `ambiguous` candidates.
  Evidence grades are carried only in the internal frozen input and never affect matching or the
  current-year decision; the API projection contains no grade or label.
- Added an explicitly `local-synthetic-only` SQLite adapter over real uploaded version snapshots,
  published extraction artifacts, verified source references, human-confirmed immutable tag and
  decision revisions, and the existing pure-Python decision lineage. No model or AWS call is made.
- Added immutable `comparison_request` and `comparison_receipt` records with actor-scoped
  idempotency, hashes, current/prior document versions, run IDs, mutation epochs, and target
  snapshot hashes. Additive schema/triggers reject update, delete, and duplicate replacement.
- Missing prior artifacts, missing approved claim snapshots, unverified sources, missing approved
  comparison keys, incompatible periods, and non-previous years never become evidence absence or
  inferred removals. Eligible cases return truthful `not_run`; duplicate keys become `ambiguous`.
- Added the canonical POST/GET HTTP boundary with editor/viewer authorization, CSRF, strict DTOs,
  10/120 per-user-per-operation rate limits, idempotency, tenant-hiding 404s, and no-store reads.
  The feature remains disabled by default through the existing `ENABLE_YEAR_COMPARISON=false` flag.
- GET and idempotent replay revalidate both pinned document versions through the guarded upload
  service read. A retention tombstone on
  either the current or prior document hides the saved result with 404 instead of leaking history.
- Added the controlled `ComparisonPage` with exported stable props, accessible controls, candidate
  terminology, removal disclaimers, grade-isolation notice, and reason-specific `not_run` copy.

Stable integration surfaces:

- `LocalComparisonStore(runs, uploads, claims, *, enabled: bool = False)`
- `build_comparisons_router(store, auth_store, *, allowed_origin: str, clock=time.time)`
- `ComparisonPageProps`: `currentYear`, `priorVersions`, optional selected ID/result/busy/callbacks

## TDD record

1. `uv run pytest tests/acceptance/test_comparison.py -q` initially exited 2 during collection with
   `ModuleNotFoundError: No module named 'proofops.application.comparisons'`.
2. After the minimal pure service/UI implementation, the exact AT-023 command passed 10 tests.
3. `uv run pytest tests/integration/test_comparison_api.py -q` initially exited 2 with
   `ModuleNotFoundError: No module named 'proofops.adapters.local.comparison_store'`.
4. The real local integration was then driven through upload, parse, extract, citation
   verification, pure rules, immutable revisions, POST, and GET; it passed after implementation.
5. The current/prior deletion regression was added before its fix and failed twice because GET
   returned 200 instead of 404. Both cases passed after GET/replay version reauthorization.
6. The missing-approval regression was added before its fix and failed because POST returned 409
   instead of 202. It now persists `not_run/approved_claim_snapshot_missing` with no candidates.

## Final exact commands and results

| Command | Actual result |
|---|---|
| `uv run pytest tests/acceptance/test_comparison.py -q` | exit 0, `10 passed in 0.16s` |
| `uv run pytest tests/integration/test_comparison_api.py -q` | exit 0, `6 passed, 2 warnings in 2.86s` |
| `uv run pytest tests/acceptance/test_comparison.py tests/integration/test_comparison_api.py tests/integration/test_local_api_composition.py tests/integration/test_deleted_document_access.py tests/unit tests/contracts tests/security -q` | exit 0, `74 passed, 2 warnings in 5.16s`; warnings are existing Starlette/httpx and AnyIO deprecations |
| `uv run ruff check packages/proofops/application/comparisons.py packages/proofops/adapters/local/comparison_store.py apps/api/src/proofops_api/routers/comparisons.py tests/acceptance/test_comparison.py tests/integration/test_comparison_api.py` | exit 0, `All checks passed!` |
| `uv run ruff format --check packages/proofops/application/comparisons.py packages/proofops/adapters/local/comparison_store.py apps/api/src/proofops_api/routers/comparisons.py tests/acceptance/test_comparison.py tests/integration/test_comparison_api.py` | exit 0, `5 files already formatted` |
| `uv run mypy packages/proofops/application/comparisons.py packages/proofops/adapters/local/comparison_store.py apps/api/src/proofops_api/routers/comparisons.py` | exit 0, `Success: no issues found in 3 source files` |
| `uv run python scripts/verify_architecture.py` | exit 0, all purity, DTO, port, composition, and read-only contract checks passed |
| `pnpm --dir apps/web build` | exit 0, TypeScript and Vite build passed; 50 modules transformed |
| `uv build --package proofops --out-dir /tmp/proofops-task023-final-build-20260909b` | exit 0, sdist and wheel built |
| `if rg -n '[[:blank:]]+$' <owned TASK-023 files>; then exit 1; else exit 0; fi` | exit 0, no trailing whitespace |

The acceptance UI check bundles React and renders `ComparisonPage` with the actual component using
ReactDOM server rendering. The separate `ComparisonWorkspace` browser E2E is owned by another
dispatch and is not claimed here.

## Migration, rollback, and not-run gates

- Migration is additive and transactional: create/check `comparison_schema` version 1, then add
  immutable guards for the two comparison record kinds in the existing local job-record table.
- Rollback disables comparison routes/writers and retains immutable receipts. Removing the guards
  or deleting history is intentionally not part of rollback.
- No dependency or lock file changed. Real product-model calls, real AWS calls/mutations,
  deployment, private customer processing, and human data/rights/legal approval are `not_run` or
  remain human-blocked; no production-readiness or corpus-accuracy claim is made.
