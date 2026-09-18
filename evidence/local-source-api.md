# Local source and quality API integration

`GET /v1/runs/{run_id}/sources/{source_id}` and `/quality` read only fence-published immutable parser evidence. The API composition shares the SQLite run store, upload originals and parser-prepared artifact root with the local worker. Original hashes, version/object identity, manifest/candidate artifacts and full rich graph are verified before reads. Unverified parser spans stay candidate; absent/conflicted/unpublished sources are never promoted.

Quality pagination uses the existing HMAC cursor with tenant/run/endpoint/limit scope, a fixed manifest and snapshot epoch, and 15-minute expiry. Cancelling a run between pages retains the original cursor epoch; different limit, tenant, expired cursor or corrupt graph cannot expose evidence.

Root actual checks:

- `uv run --no-sync pytest tests/integration/test_source_api.py tests/integration/test_local_api_composition.py tests/acceptance/test_tracks.py tests/acceptance/test_coverage.py tests/acceptance/test_citations.py tests/acceptance/test_retrieval.py tests/acceptance/test_injection.py tests/security/test_prompt_injection.py -q`: 124 passed, two existing TestClient deprecation warnings.
- Focused Ruff passed. `uv run --no-sync mypy --check-untyped-defs apps/api/src/proofops_api/routers/sources.py apps/api/src/proofops_api/composition.py packages/proofops/application/coverage.py packages/proofops/application/tagging/tracks.py packages/proofops/application/evidence packages/proofops/adapters/aws/opensearch.py`: no issues in eight source files.
- Parser/lifecycle/job/observability regression: 94 passed. An initial command referred to nonexistent test_telemetry.py and ran no tests; corrected to test_observability.py before acceptance.
- Local generated PDFs only. Live model, AWS, customer corpus and production deployment remain not_run.

No API schema or SQL table migration is needed. Cursor decoding adds endpoint scoping with audit as its compatible default. Rollback stops new reads/workers and preserves originals, immutable snapshots and published checkpoints.

## Extracted claims reads

The composed API now lists verified immutable extraction snapshots through `/claims`, with original source quotes, null decisions/tracks until tagging, bounded signed pagination and the fixed optional filters. Before a committed extraction it returns 409; an existing claim detail returns TAGGING_NOT_PUBLISHED until the separate evidence/tagging snapshot exists, rather than inventing that packet, assurance or model receipts. Missing/foreign claims share 404. This pending detail response is not a completed TASK-010 claim-detail implementation.

Failing-first `test_claim_api.py` confirmed the router was absent. After implementation `uv run --no-sync pytest tests/integration/test_claim_api.py tests/integration/test_source_api.py tests/integration/test_local_api_composition.py -q` passed 3 cases, including multiple actual extracted claims, cursor filters/expiry, null decisions, tenant isolation and no-store. Ruff and checked-body mypy passed for the new router.

Combined API/request-control/auth/session/registry/preflight acceptance subsequently passed
136 tests. Ruff passed and mypy checked all 17 API source files without errors. Each source,
quality and claim read consumes its independent authenticated-user request bucket.

## Isolated API installation

The API's existing proofops dependency now includes its already-pinned parsing extra. `load_verified` checks the installed OpenDataLoader JAR digest and pdfplumber version; installing auth/verification alone omitted those required read-verification artifacts.

- `uv lock --offline`: same 73 packages, only existing API extra/dependency edges changed.
- `uv build --offline --package proofops-api` and `uv build --offline --package proofops`: wheel/source builds passed.
- A fresh Python 3.12 venv installed only the two wheels and their dependencies, constrained to `uv export --frozen --package proofops-api --no-emit-workspace --no-hashes --no-dev`. Initial offline installation could not resolve cached Pillow metadata; the lock-constrained normal install succeeded with 30 packages and no version drift.
- From `/tmp/proofops-api-isolated.9yGEAi`, isolated Python `-I` imported the wheel API, read the packaged OpenDataLoader JAR, verified pdfplumber 0.11.10, and exercised actual HTTP health=200 and unauthenticated claims=401. No workspace imports, real model call, AWS action or customer document was used.
- These existing parser dependencies retain the previously recorded license/notices review; no external package or version was added.

## Five-minute local original view

`POST /v1/runs/{run_id}/sources/{source_id}/view` now verifies the live viewer session,
CSRF/Origin and the immutable source chain, then returns the fixed Download DTO. The
local URL uses the existing durable HMAC key, binds tenant/user/run/source/document
version/manifest/PDF hash, and expires after 300 seconds. Redemption rechecks current
session membership and original bytes; a signed URL alone is insufficient. Candidate
or conflicted sources remain unverified but can still open the original PDF for review.

The private local transport returns the bounded original PDF with no-store/private,
nosniff and no-referrer headers. The page fragment is physical PDF page numbering;
this does not claim a completed PDF highlight UI. Vite proxies `/local/sources` to the
same configured API. Byte ranges are deferred until large-file viewing needs them.
No new DB table, dependency, external URL fetch or cloud signed URL is introduced.

The new integration first failed because the route/configuration was absent. Actual
local PDF tests then verified identical returned bytes/hash, expiry, altered token,
source/user/tenant substitution, CSRF denial, 60/min issuance (including denial before
budget use), corrupted original refusal and session rejection. Combined source/claims/
composition/request-limit checks passed 20 tests; the additional composed route mounting
check passed. Scoped Ruff and checked-body mypy passed (two API files).

OpenAPI issuance rate metadata was corrected to docs/07's explicit 60/min policy;
the reason and compatible rollback are in evidence/contract_review_resolution.md.
Actual browser PDF rendering, cloud URLs and customer PDFs remain not_run.
