# Local catalog list API evidence

Date: 2026-09-09 (Asia/Seoul)

## Scope

Implemented the fixed local-only list routes:

- `GET /v1/documents`
- `GET /v1/documents/{document_id}/versions`
- `GET /v1/runs`
- `GET /v1/rule-packs`

The routes use the existing authenticated viewer boundary and shared
`AuthStore` per-user/per-operation read limiter (120/minute). Successful JSON
responses are `Cache-Control: no-store` and contain only the fixed page/item
fields.

## Pagination and local schema

`proofops.adapters.local.catalog_pages` now owns the two exact shared entry
points: `initialize(db)` and `page(db, *, tenant_id, endpoint, query, cursor,
limit, now, load_items)`. Both require the caller's active SQLite transaction;
the helper opens no connection and never commits. `catalog_schema` is an
independent strict version-1 marker, while the existing `catalog_cursor_key`
and `catalog_list_snapshots` remain additive and data-compatible.

Each cursor is HMAC signed and binds tenant, endpoint, canonical parent/filter
query plus limit, expiry, snapshot epoch, and offset. Loaders are consumed as
iterables with immediate fail-closed limits of 10,000 rows and 8 MiB per
snapshot; committed storage is capped at 32 snapshots/32 MiB per tenant and
256 snapshots/128 MiB globally after 15-minute expiry cleanup. Identical
unexpired scope+payload snapshots reuse the original row, epoch, and expiry, so
ordinary repeated reads do not exhaust capacity. A loader may return
`{"items": iterable, "snapshot_epoch": original_run_mutation_epoch}`; that
epoch is stored in the payload and returned on every continuation without a
new head read.

Documents, document versions, and runs retain `created_at` plus UUID order.
The fixed `RulePack` contract has no `created_at`, so the local adapter uses the
first immutable revision rowid as creation order; the UUID remains the
deterministic tiebreak contract once a timestamp exists.

Rollback is non-destructive: stop new catalog writers and run the old readers,
which ignore the private catalog tables. Retain `catalog_schema`, the durable
key, and all private snapshots (including expired rows); no DROP or cleanup is
executed as part of rollback, and business/immutable records are unchanged.

## Failed-first evidence

Command:

```text
uv run pytest tests/integration/test_catalog_lists.py -q
```

Initial result: exit 1, `3 failed`; the document and run collections returned
405 and the rule-pack collection returned 404 because the four GET handlers did
not exist. A later focused RED check changed rule-pack IDs to insertion order
`3,1,2`; it failed because the first implementation incorrectly sorted by
effective date and ID, then passed after using immutable local creation order.

The shared-helper repair first failed with `3 failed` because
`proofops.adapters.local.catalog_pages` did not exist. Focused follow-up tests
then failed twice: an oversized generator was consumed past its first item and
an identical read created a second snapshot; both passed after streaming byte
accounting and identical-snapshot reuse were implemented.

## Verification

```text
uv run pytest tests/integration/test_catalog_lists.py -q
7 passed, 2 dependency deprecation warnings

uv run pytest tests/integration/test_catalog_lists.py tests/acceptance/test_upload.py tests/integration/test_run_lifecycle.py tests/acceptance/test_rulepack_api.py tests/integration/test_local_api_composition.py tests/contracts/test_package_contracts.py -q
109 passed, 2 dependency deprecation warnings

uv run pytest tests/integration/test_claim_api.py tests/acceptance/test_reviews.py -q
31 passed, 2 dependency deprecation warnings

uv run ruff check <shared helper, 3 delegates, catalog test>
All checks passed

uv run mypy <shared helper and 3 delegates>
Success: no issues found in 4 source files

uv run python -c <direct run_store source_view limit=0 cursor assertion>
source_view limit=0 cursor: PASS
```

`tests/integration/test_source_api.py` was also sampled and reached successful
source-view ticket issuance and PDF retrieval, then had one failure in the
concurrently edited page-preview route (`application/pdf` versus `image/png`).
Those source router/test files are outside this repair; the direct assertion
above isolates the required untouched `source_view`, limit-0 cursor contract.

A temporary composed-app assertion also passed for all four generated OpenAPI
operation IDs, viewer security metadata, 120/minute limits, cursor/limit/path
parameters, and fixed page response references.

The integration test exercises real FastAPI HTTP calls and file-backed SQLite,
including cross-replica cursor reuse, default page envelopes, deterministic
pagination, tenant isolation, foreign-parent 404, endpoint/limit scope,
tampered and expired cursors, concurrent inserts, mutable heads, and exclusion
of tenant/approval/internal storage fields. It also verifies the pre-helper
signed cursor/raw-list snapshot format remains readable while its scope is
still valid.

Browser E2E was `not_run` because the dispatched web worker owns the UI and
harness. Build and dependency audit were not rerun because this repair adds no
dependency and the dispatch explicitly excluded them absent new risk. AWS and
live-model checks were `not_run` by task restriction.
