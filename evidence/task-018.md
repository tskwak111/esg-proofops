# TASK-018 · 유예·기준 효력 — Evidence (FR-018 / AT-018)

Coordinator acceptance repair: three new malformed-entry cases reproduced two
unhandled type errors (list/dict outcome) and an empty end date silently becoming
an unlimited period. Outcome type checking and explicit null handling fixed the
shared entry boundary. The same three tests now pass without weakening assertions.
`uv run --no-sync pytest tests/acceptance/test_regulatory.py tests/acceptance/test_rulepacks.py tests/contracts/test_package_contracts.py -q`
exited 0: 81 passed (14 regulatory, 38 rulepack, 29 contract).
Scoped Ruff and Mypy both exit 0. Worker ownership transferred to the separate
TASK-037 repair before its completion delivery was acknowledged.

## Scope and result

Implemented the pure `resolve_deferral(CompanyContext, RulePackSnapshot)` domain
boundary. It reads `regulatory/timeline.yaml` only through TASK-025's immutable,
self-verifying snapshot, and returns `required` or `advisory` only when exactly
one explicit half-open entry matches the reporting date and opaque company
conditions. The snapshot tenant must match the company context, pack approval
must contain a valid UTC timestamp and approver, and automatic legal
applicability must be explicitly enabled in an approved timeline; every
unverified, disabled, cross-tenant, unmatched, malformed, or overlapping case
returns `undetermined`. The module contains no real regulatory dates, asset
thresholds, violation labels, or immunity conclusions.

The acceptance fixtures are explicitly synthetic local-only timeline data. They
do not claim that any real company is covered, exempt, non-compliant, or protected
by safe harbor.

## Failing-first evidence

1. Added `tests/acceptance/test_regulatory.py` before production code.
   `uv run --no-sync pytest tests/acceptance/test_regulatory.py -q` failed during
   collection with `ModuleNotFoundError: No module named
   'proofops.domain.regulatory'` (exit 2).
2. Added the bare-string condition boundary case before its fix. The same command
   produced `1 failed, 6 passed`; `CompanyContext.condition_ids` incorrectly
   accepted a string as individual characters.
3. Added the `datetime`/`date` boundary case before its fix. The same command
   produced `1 failed, 7 passed`; `datetime` is a `date` subclass and would later
   cause incompatible comparisons.
4. Added malformed approval timestamp coverage before its fix. The same command
   produced `1 failed, 8 passed`; non-empty invalid text was incorrectly accepted
   as approval metadata.
5. Added immutable RulePackSnapshot consumption before replacing the standalone
   timeline projection. The test failed with `AttributeError: 'RulePackSnapshot'
   object has no attribute 'is_approved'`, proving the old boundary did not consume
   the accepted TASK-025 snapshot.
6. Added tenant/company identity to `CompanyContext` before implementation. The
   acceptance run produced `11 failed` with the expected unexpected-keyword error;
   the minimal implementation then validated canonical UUIDs and made a
   cross-tenant snapshot resolve to `undetermined`.

Each failure was fixed in the shared domain boundary, not in callers or test
doubles. The tests call real immutable dataclasses and the real pure resolver;
there are no mocks.

## Final verification (2026-09-09 KST, repository root)

- `uv run --no-sync pytest tests/acceptance/test_regulatory.py -q`
  → **11 passed in 0.01s**.
- `uv run --no-sync pytest tests/acceptance/test_regulatory.py
  tests/acceptance/test_rulepacks.py tests/contracts tests/unit -q --tb=short`
  → **94 passed in 1.50s**, two upstream FastAPI/Starlette deprecation warnings.
  This includes the real HTTP package-contract integration test and the TASK-025
  approved rule-pack dependency regression.
- `uv run --no-sync ruff check packages/proofops/domain/regulatory.py
  tests/acceptance/test_regulatory.py`
  → **All checks passed**.
- `uv run --no-sync ruff format --check packages/proofops/domain/regulatory.py
  tests/acceptance/test_regulatory.py`
  → **2 files already formatted**.
- `uv run --no-sync mypy packages/proofops/domain/regulatory.py
  tests/acceptance/test_regulatory.py`
  → **Success: no issues found in 2 source files**.
- `uv run --no-sync python scripts/validate_package.py`
  → **Status: passed; 695/695 checks**, explicitly documentation/contracts
  only, not an application/model/cloud/PDF benchmark.
- `uv run --no-sync python scripts/check_licenses.py`
  → **supply-chain gate: PASSED**; human license/data-rights approvals and
  deployed-image verification remain separate release gates.
- `uv build --package proofops --out-dir
  /tmp/proofops-task018-build-final2`
  → source distribution and wheel built successfully; `unzip -l ... | rg
  'proofops/domain/regulatory.py'` confirmed the new module is packaged.
- `git diff --check -- packages/proofops/domain/regulatory.py
  tests/acceptance/test_regulatory.py`
  → exit 0, no output.

## Blocked / not_run gates

- The current repository timeline remains draft,
  `verification_status=source_provided_unverified`, with no entries and
  `automatic_legal_applicability_enabled=false` under GAP-009. No real legal
  applicability or safe-harbor conclusion was enabled or tested.
- `GET /v1/runs/{run_id}/summary` regulatory serialization/persistence was
  **not_run**: the task assigns only the pure domain module/test, and no regulatory
  API wiring or approved live timeline exists yet. No shared API/schema files were
  changed.
- Real model calls, AWS mutation/staging, private customer data, legal approval,
  data-rights approval, E2E browser testing, and deployed-image verification were
  **not_run**.

No dependency, lockfile, shared contract, commit, or push was added.
