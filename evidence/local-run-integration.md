# Local run lifecycle integration

Schema/migration contract (recorded before implementation): additive component v1 tables `run_schema`, `run_snapshots`, `run_idempotency`, and `run_cursor_key`; existing job, usage, rule-pack and audit schemas remain v1. Run snapshots are immutable JSON containing ready UploadService document-version metadata/object hash, approved consent/runtime/rights artifacts and hashes, full RulePack content/version/hash, trusted parser hash and immutable budget limits. Existing rows/APIs remain readable. Unknown component versions fail closed. No root composition, public contracts or dependency changes.

One file-backed SQLite database is shared by RunStore, JobStore, UsageStore and RulePackStore. `BEGIN IMMEDIATE` serializes creation and active-pointer selection; run metadata, frozen snapshots, parse job/outbox, budget, canonical audit and 24-hour replay response commit or roll back together. Existing cancel/retry job transactions already include immutable action snapshots, audit and idempotency; expose only the pinned public Run projection. Audit pagination uses a persisted HMAC key, tenant/run/endpoint/limit-bound 15-minute cursors and immutable sequence cutoff plus run epoch.

Retaining rollback: stop API writers/workers, back up the SQLite file and object directory, restore the prior application while retaining new tables and old immutable versions/audit. Do not drop rows, rewrite accepted document versions, or re-enqueue committed jobs. This is local synthetic persistence only; AWS, real model execution, customer PDFs and human/rights approvals remain not_run.

Root interface: `LocalSQLiteRunStore(path, *, rulepacks=None)` exposes `jobs` and `usage`; `RunService(store, uploads, registry, *, parser_profile_hash=None, budget_limits=None, allowed_regions=(), build_result=None, clock=time.time, app_env="local", model_adapter="synthetic")`; `build_runs_router(service, auth_store, *, allowed_origin, app_env="local", model_adapter="synthetic")`. Missing trusted configuration keeps run creation blocked. Constructors do not insert approvals. Root alone wires these factories.

Implemented and verified locally: POST create/cancel/retry and GET run/cost/audit factories (six routes), strict existing RunCreate request validation, public Run/Cost/AuditEventPage projections, ready document/version snapshots, approved profile artifacts and original artifact hashes, exact active RulePack content/version/hash, trusted parser/budget/build inputs, real queued parse job/outbox, canonical audit and 24-hour idempotency. Root constructor defaults remain fail-closed. No normal-app synthetic approvals are inserted.

The consent allowlist explicitly authorizes the immutable uploaded `rights_profile_id`; a display label is never treated as permission. `snapshot(tenant_id, run_id)` returns the retained internal envelope for worker composition; its `input_hash` is the initial JobMessage input hash. Parser stage execution remains queued until a real worker claims it. Cancel/retry reuse the accepted job engine and audit transaction without changing existing job APIs. Two queued/running runs per tenant are enforced under the creation write lock; shared per-user HTTP rate limiting remains a root composition concern.

## Executed checks

1. Fail-first: `.venv/bin/python -m pytest tests/integration/test_run_lifecycle.py -q` initially reported **15 failures** because the lifecycle module did not exist. An initial plain pytest invocation could not resolve the reusable `tests.acceptance` helpers; the documented `python -m pytest` invocation resolves the repository namespace. Later regression checks reproduced exact-response JSON ordering, same-connection tuple-row compatibility, tenant run-limit and fixed operation-ID failures before their corrections.
2. Final focused suite (exit 0):
   ```sh
   .venv/bin/python -m pytest tests/integration/test_run_lifecycle.py tests/acceptance/test_jobs.py tests/acceptance/test_cost.py tests/acceptance/test_rulepack_api.py tests/acceptance/test_audit.py tests/acceptance/test_advertising.py tests/acceptance/test_preflight.py tests/acceptance/test_upload.py tests/contracts/test_package_contracts.py -q --tb=short
   ```
   **257 passed, 2 existing Starlette/httpx/AnyIO deprecation warnings, 7.66s.** This includes **33 lifecycle HTTP integration tests** and the selected accepted adapter/contract checks, not the full WIP repository suite.
3. Lint (exit 0, `All checks passed!`):
   ```sh
   .venv/bin/ruff check packages/proofops/application/runs.py packages/proofops/adapters/local/run_store.py apps/api/src/proofops_api/routers/runs.py tests/integration/test_run_lifecycle.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/usage.py packages/proofops/adapters/local/rulepack_store.py
   ```
4. Type check (exit 0, `Success: no issues found in 6 source files`):
   ```sh
   .venv/bin/mypy --check-untyped-defs packages/proofops/application/runs.py packages/proofops/adapters/local/run_store.py apps/api/src/proofops_api/routers/runs.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/usage.py packages/proofops/adapters/local/rulepack_store.py
   ```
5. Offline package builds (both exit 0):
   ```sh
   uv build --package proofops-api --wheel --offline --no-create-gitignore --out-dir /tmp/proofops-run-integration-build
   uv build --package proofops --wheel --offline --no-create-gitignore --out-dir /tmp/proofops-run-integration-build
   ```
   ZIP inspection asserted the wheels contain `proofops/application/runs.py`, `proofops/adapters/local/run_store.py` and `proofops_api/routers/runs.py`.

Security/integrity cases exercised: actual HTTP editor capability vs viewer/reviewer, active session tenant, CSRF and configured Origin, missing/foreign lookup parity, strict payload and 1-based actual page count, real concurrent instances, same-key exact response bytes, stale 412, failed create/cancel audit rollback, immutable snapshots and audit, signed cursor cutoff/expiry/limit/run binding, approved-mode and region/profile/build gates, zero calls observed at patched model invocation boundaries, exact Decimal cost and unknown-not-zero cost. Active-pack replacement changes only new runs and the original audit hash chain verifies through the accepted audit adapter.

Not run / retained gates: AWS/DynamoDB/SQS, live model calls, customer PDF parsing, human/rights/legal/model account approval, complete PDF-to-decision worker execution, and browser E2E. Root main/composition wiring, public contracts/DTO source, registries/uploads/auth, manifests/locks and Git were not edited. No commit, push or cloud change was performed.

## Coordinator acceptance and composition

Root mounted all six routers using the same local database and existing immutable
uploads/registry/rulepack stores. Missing trusted parser/budget/build inputs still
block creation. The composed unauthorized run lookup first returned router-missing
404; after wiring it returns 401, and an authenticated missing run has the required
opaque error envelope.

The ordinary `uv run --no-sync pytest` command initially failed to import shared
test fixtures. The root pytest config now explicitly includes the repository root,
so the documented runner works without per-command PYTHONPATH workarounds.

A new regression exposed retry bypassing the two-active-runs tenant limit (202
instead of 429). Create and retry now use the same active-run counter inside their
write transaction; rejected retry leaves revision and audit unchanged.

`uv run --no-sync pytest -q tests/integration/test_run_lifecycle.py tests/integration/test_local_api_composition.py tests/acceptance/test_jobs.py tests/acceptance/test_cost.py tests/acceptance/test_audit.py`
exited 0: **89 passed**, two existing dependency warnings. Targeted Ruff passed;
`mypy --check-untyped-defs` over run service/storage, job/usage/rulepack hooks and API
router/main/composition passed for **8 source files**. Parser executor and shared
per-user request limiting remain follow-up integration work, not completed here.
