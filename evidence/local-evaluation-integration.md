# Local evaluation integration evidence

Date: 2026-09-09
Scope: synchronous local CLI evaluation and read-only API projection.

## Schema and rollback contract (defined before implementation)

Schema version 1 is additive and owns only `evaluation_schema` and
`evaluation_artifacts`. The artifact table uses `(tenant_id, evaluation_id)` as its primary key,
stores the canonical rich report JSON and its SHA-256, and has `BEFORE UPDATE` and
`BEFORE DELETE` triggers that abort with `immutable evaluation artifact`.

Initialization runs in `BEGIN IMMEDIATE`, accepts only the empty schema or version 1, and rolls
back the whole initialization or insert on error. Runtime rollback is non-destructive: stop wiring
the CLI/router/store, retain the versioned immutable rows for audit/export, and let the later
retention task own deletion; no down migration is implemented here.

## Verification log

The local CLI reads three separate, strict JSON files (predictions, verified gold, and company
split manifest), computes the pure evaluator result, and inserts one immutable rich report into
`LOCAL_DATABASE_PATH`. The report retains the evaluator version, explicit synthetic-fixture flag,
SHA-256 of all three input byte streams, per-metric status and denominator, and ordinal confusion;
the API projects only the fixed `Evaluation` DTO fields and never returns gold, source values,
input hashes, the fixture flag, or the rich-only metric fields.

Test-first failure:

- `uv run pytest tests/integration/test_evaluation_api.py -q` — **failed as expected**:
  `8 failed, 2 warnings in 0.52s` before the store and CLI existed.

Final scoped verification:

- `uv run pytest tests/integration/test_evaluation_api.py -q` — **passed**:
  `11 passed, 2 warnings in 0.93s`. The warnings are dependency deprecations from
  FastAPI/Starlette's current test client and anyio alias.
- `uv run ruff check evaluation/cli.py packages/proofops/adapters/local/evaluation_store.py apps/api/src/proofops_api/routers/evaluations.py tests/integration/test_evaluation_api.py`
  — **passed**: `All checks passed!`.
- `uv run ruff format --check evaluation/cli.py packages/proofops/adapters/local/evaluation_store.py apps/api/src/proofops_api/routers/evaluations.py tests/integration/test_evaluation_api.py`
  — **passed**: `4 files already formatted`.
- `uv run mypy evaluation/cli.py packages/proofops/adapters/local/evaluation_store.py apps/api/src/proofops_api/routers/evaluations.py`
  — **passed**: `Success: no issues found in 3 source files`.

The integration test runs the CLI as a real subprocess, reopens the same SQLite database through
the store, and reads the artifact through HTTP. It also checks exact input hashes, absence of a
model-cache table, immutable update rejection, tenant isolation, admin/viewer authorization,
120/min/user throttling, no-store response policy, exact DTO projection, safe corruption handling,
and rejection of unknown fields, non-finite values, wrong primitive types, oversized input, future
schema versions, and tenant/dataset/split/out-of-dataset-claim identity mismatches.

Human gold review, real model calls, AWS integration, customer PDFs, broad WIP suites, build, and
security audit: **not_run** (outside this local synthetic integration scope). The optional upstream
metrics remain `not_run` with null values and explicit denominators; no values were fabricated.

Coordinator review reproduced an unbounded read if input grew after metadata inspection.
The focused growing-file check failed first at read(-1); the CLI now checks regular
files and reads at most 1 MiB + 1 byte. The combined evaluator/CLI suite passed
25 tests; scoped Ruff and mypy passed. API composition now mounts this router.
