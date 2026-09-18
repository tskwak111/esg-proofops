# TASK-030 budget and cost evidence

## Approved scope and local schema contract (before implementation)

Use the three assigned files only plus this evidence document. Typed calls,
limits, prices, usage, repository port and pure Decimal cost projection live in
`application/budget.py`; `adapters/aws/usage.py` explicitly provides a
local-synthetic-only SQLite repository, with no implied AWS capability.

Local schema v1 adds component-owned `usage_schema`, `usage_runs` and
`usage_attempts` tables, preserving other components and global user_version.
Run identity/policy and attempt reservation inputs are immutable. Reservation
admission and usage settlement each use an actual SQLite write transaction;
usage is write-once and unknown consumption retains the conservative reservation.
Unknown versions fail closed. Rollback stops local workers and retains these
local records, then reverts the adapter; no destructive downgrade or production
DB/API contract migration is introduced.

Implementation sequence: failing acceptance tests → minimum real persistence and
budget calculation → race/reopen/unknown-price/immutable-attempt validation →
focused lint/type/unit/contract/integration/build/security checks. No new dependency,
model call, AWS mutation, shared contract change, commit or push. Caller-resolved
preflight, actor/tenant authorization and HTTP/root wiring remain integration gates.

Before final implementation review, schema v1 was additively extended with
`usage_prices(snapshot_id PRIMARY KEY, payload_json)`. Approved price snapshot IDs
are global within the shared local database; a reused ID must carry the identical
model/region/rates/timestamp payload even across tenants or runs. Reservation and
snapshot registration share one transaction; failed admission rolls back both.

## Implemented behavior and boundaries

- `BudgetCall` preserves tenant/run/document version, logical request ID, attempt,
  role/model/region, model binding hash, actual request signature and replica.
  Per-request model/document/replica identity cannot change. Transient retries
  keep the request signature; one schema repair may record its changed prompt
  signature without rewriting the original attempt.
- `BudgetLimits` and `RoleLimit` are immutable, explicit server policy inputs.
  Reservation admission checks run input/output limits, role call count, per-call
  input/output/context limits and at most three total attempts. Stored policies
  cannot silently increase. Rejected admission writes neither an attempt nor a
  new price snapshot. There are no topic quotas or hidden sampling fallbacks.
- The local sequence is `reserve_budget` → `mark_dispatched` → `record_usage`.
  Duplicate reservations return false; dispatch is a single CAS transition, so
  duplicate workers cannot re-invoke the same reserved attempt. Reserved and
  dispatched tokens both count against capacity across actual DB connections.
- A new attempt requires the preceding attempt to have been released before
  dispatch or settled with a permitted transient/schema error. Pending,
  dispatched and succeeded attempts cannot be retried. Citation failures are not
  network retries; schema repair is limited to one and counts inside the total
  attempt budget. A cancelled attempt without a permitted error is not retryable.
- `release_budget` compensates only work that was never marked dispatched.
  Dispatched timeouts cannot refund unknown usage. A response-cache hit is an
  explicit release flag, preserved once, counted as a cache hit and never as a
  provider invocation or fabricated provider tokens. Provider prompt cache reads
  remain actual provider usage and use their own recorded rates.
- `record_usage` persists failure/cancellation as well as success, request ID,
  provider response ID when available, latency, cached read/write tokens and the
  complete frozen price snapshot identity/hash. Duplicate identical settlement is
  idempotent; different usage cannot overwrite an earlier ledger entry.
- Actual known tokens replace reserved maxima when settling; unknown counts retain
  the reservation. Actual overrun reports are persisted rather than discarded to
  make a budget look compliant, and future admissions then fail. Model usage that
  remains unknown is not automatically refunded or retroactively rewritten.
- Decimal rates are USD per million tokens. Floats, negative/non-finite rates,
  negative/bool counts and cache counts exceeding total input are rejected.
  `input_tokens` means total input including disjoint cached read/write subsets;
  provider-specific raw fields must be normalized to this definition upstream.
- `cost_summary` matches the unchanged Cost JSONSchema. No configured price,
  missing required cache rate or incomplete usage gives `amount=null`;
  all-unpriced is `unknown_cost`, while some known calls alongside incomplete
  ones are `partial` with a null total (never an unlabeled subtotal). Complete
  calls use exact Decimal sums. A mixed set of complete price snapshots can have
  a known amount while aggregate `pricing_snapshot_id=null`; per-call IDs/hashes
  remain available in the ledger. Token fields are known reported subtotals,
  not invented estimates for absent provider metadata.

## TDD and review evidence

All commands used actual local persistence and synthetic inputs, without mocking
the budget/store behavior.

- `uv run --no-sync pytest tests/acceptance/test_cost.py -q`: initially exit 2 at
  collection because `proofops.adapters.aws.usage` did not exist.
- After initial implementation, a role-admission test failed because request
  identity checking preceded unknown-role rejection; role limit admission now
  executes before that comparison, and all 14 initial cases passed.
- Added the exhausted-input boundary: same command exited 1 with `1 failed,
  20 passed`, because zero-input new work was admitted at 100% consumption.
  Admission now blocks when either token dimension is exhausted.
- Explicit response-cache compensation test initially failed with unsupported
  `response_cache_hit`; the release record now tracks it without provider billing.
- Coordinator review tests initially exited 1 with `3 failed, 21 passed`: live
  attempts could overlap as retries, a price ID could alias across tenants/runs,
  and citation failures could retry. State checks, bounded schema repair and the
  transactional global price identity table fixed those paths.
- A final repair-signature regression exited 1 with `1 failed, 24 passed`; schema
  repair now preserves a distinct actual request signature per attempt while
  normal transient retries retain theirs and all other logical identity fields.
- Ruff found import ordering/long lines; formatting corrected them. Mypy found
  Decimal exponent typing and a nullable prior usage guard; both were corrected,
  including an explicit fail-closed guard for missing settled usage.

## Exact verification commands and observed results

Date: 2026-09-09 Asia/Seoul.

| Command | Actual result |
|---|---|
| `uv run --no-sync pytest tests/acceptance/test_cost.py -q` | exit 0; `25 passed in 0.20s` |
| `uv run --no-sync pytest tests/acceptance/test_cost.py tests/acceptance/test_preflight.py tests/contracts/test_package_contracts.py tests/unit -q` | exit 0; 133 passed; two existing FastAPI/Starlette deprecation warnings |
| `uv run --no-sync ruff check packages/proofops/application/budget.py packages/proofops/adapters/aws/usage.py tests/acceptance/test_cost.py` | exit 0; `All checks passed!` |
| `uv run --no-sync ruff format --check packages/proofops/application/budget.py packages/proofops/adapters/aws/usage.py tests/acceptance/test_cost.py` | exit 0; `3 files already formatted` |
| `uv run --no-sync mypy packages/proofops/application/budget.py packages/proofops/adapters/aws/usage.py tests/acceptance/test_cost.py` | exit 0; `Success: no issues found in 3 source files` |
| `uv run --no-sync python scripts/verify_architecture.py` | exit 0; domain purity, fixed schema, local composition and deployment fail-closed checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task030-build` | exit 0; source distribution and wheel built |
| `git diff --check -- packages/proofops/application/budget.py packages/proofops/adapters/aws/usage.py tests/acceptance/test_cost.py evidence/task-030.md` | exit 0; no whitespace errors |

The focused tests include eight competing reservation connections, actual
separate-process settlement followed by reopen, immutable usage/policy/price
checks, schema coexistence without altering global user_version, and refusal of a
newer schema. These provide local integration/end-to-end and security evidence
for the assigned task; the document validator is not treated as an app test.

### Concurrent external WIP regression

`uv run --no-sync pytest tests/acceptance/test_cost.py tests/acceptance/test_jobs.py
tests/acceptance/test_preflight.py tests/contracts/test_package_contracts.py
tests/unit -q` exited 2 during collection because TASK-022's followup changes to
`test_jobs.py` imported not-yet-created `proofops.adapters.local.audit_store`.
The coordinator was informed. Those files belong to that worker and were not
edited or weakened; final jobs/audit combined regression remains with the
coordinator after the audit followup is ready. Independent cost/preflight/contracts
and unit tests passed as reported above.

## Integration handoff / not_run

- `LocalSQLiteUsageStore(path)` is explicitly `local-synthetic-only` and does not
  instantiate AWS clients. Use the server-controlled shared LOCAL_DATABASE_PATH
  only in authorized local composition. No main/composition/DTO/API/contract or
  TASK-028/TASK-022 file was changed.
- Create the frozen run budget from server limits and approved TASK-029 model
  binding capacities. Server callers must resolve tenant/role authorization,
  approved binding and current run cancellation/lease state before model dispatch;
  a stored binding hash is provenance, not proof of approval. Provider integrations
  must honor the dispatch CAS and reconcile every known success/failure usage.
- `cost_summary(store, tenant_id, run_id)` is the pure Cost projection for future
  `GET /v1/runs/{run_id}/cost` wiring. The router must derive the tenant from the
  authenticated session and authorize viewer access to the run. No HTTP endpoint
  or browser E2E is claimed as implemented by this task.
- Real models/tokenizer/count API, AWS/DynamoDB accounting, actual price retrieval,
  live cancellation/model integration, canonical audit-chain billing events,
  deployment, browser E2E, private documents and legal/data-rights approvals:
  not_run. No real model IDs, ARN values, prices, performance or accuracy figures
  were fabricated; test model/region/price identifiers are explicitly synthetic.
- Local SQLite serializes writers and scans one run's bounded attempt history;
  distributed production accounting needs the approved DynamoDB transaction
  adapter. Pending/unknown dispatches retain their allocations until a separately
  authorized reconciliation can establish actual usage; there is no unsafe TTL
  refund. No new dependencies, commit or push.
