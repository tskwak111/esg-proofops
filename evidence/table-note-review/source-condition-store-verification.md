# Source-condition revision persistence

This is the persistence prerequisite of `docs/source-condition-review-contract.md`,
not source approval, numeric-check integration or completed service acceptance.
The existing SQLite review adapter now records independent immutable source review
snapshots without requiring fabricated claim tags or modifying historical parser data.

Publication pins the supplied internal loader snapshot, records system actor/time
and appends an audit event. Revision writes reuse one database transaction for
CAS, audit, idempotency and mutation epoch. A callback will perform the application
validation; this callback is not exposed as an HTTP interface. Current writes do
not clear source issues, approve ownership, change grades or invoke a model.

Runnable regressions in `tests/integration/test_source_condition_store.py` cover
simultaneous writes (one successor and one 412), exact retries after later revisions,
changed-request conflicts, historical reads, injected audit failure rollback and
retry, initial audit idempotency, malformed request types, viewer/foreign-tenant
rejection, unknown schema rejection, immutable UPDATE/DELETE/REPLACE protection and
a stale mutable head pointing at an older valid immutable revision. Shared reads and
publication retries reject that stale head; historical reads intentionally retain it.

Orca review: task `task_971f61d7f2df`, dispatch `ctx_7165f66fa5b5`, settled success
message `msg_976372cedc9b`. The reviewer independently exercised rollback after a
mutation-epoch failure, cross-run idempotency, authorization and all implemented
immutable kinds. Its missing receipt-kind guard finding was reproduced with a
failing test and fixed before receipt writers are introduced. The worker was released
and its delivery acknowledged. No claim of an API-level exploit or source approval
was made for this unfinished persistence layer.

Verification commands:

- `uv run pytest -q tests/integration/test_source_condition_store.py tests/acceptance/test_reviews.py`:
  31 passed, two existing dependency deprecation warnings.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 282 files formatted.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
  passed, 167 files; existing notes about unchecked untyped function bodies retained.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv build --all-packages`: passed; four Python packages.
- `uv run python scripts/validate_package.py`: 763 passed; documents/contracts only.

Final `uv run pytest -q`: **1912 passed**, two existing dependency warnings,
136.26 seconds. Private log:
`.local/note-review-integration/source-condition-store-final-full.log`.
New source-condition
HTTP acceptance, browser E2E, native source confirmation, effective source-view
replay, numeric receipts and shared consumer publication remain **not_run**.
Existing security/integration/contract/staging-gate tests run in the Python suite;
they are not substitutes for the missing new application path. No dependencies,
frontend changes, push, deployment, AWS calls or actual model calls in this slice.
