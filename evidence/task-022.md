# TASK-022 — 감사 이력 / FR-022 / AT-022

Date: 2026-09-09 (Asia/Seoul)

## Actual implemented scope

- Added a file-backed, explicitly `local-synthetic-only` SQLite audit adapter. It uses only
  additive `audit_`-prefixed tables in the same `LOCAL_DATABASE_PATH`; it does not change
  `PRAGMA user_version` or other components' tables.
- Added schema version 1 with `audit_schema`, per-tenant/per-run `audit_heads`, and immutable
  `audit_events`. Unknown schema versions fail closed. SQLite primary/unique keys implement event
  put-if-absent, and the HEAD update includes the expected sequence/hash condition.
- `append_audit_transaction(connection=...)` uses the caller's open transaction and never commits.
  The standalone store wraps it in `BEGIN IMMEDIATE`; the TASK-028 job store calls it inside the
  existing cancel/retry transaction.
- Cancel/retry now commit the run/job mutation, 24-hour idempotency record, existing immutable full
  before/after action envelope, canonical audit event, and audit HEAD together. Injecting a real
  SQLite audit insert failure rolls all of them back, and the same idempotency key can then succeed.
- `ChangeSet` and `AuditEvent` now carry the result/action revision, and revision is included in the
  canonical event hash and DynamoDB request item.
- Audit rows contain only tenant/run/event/target identifiers, sequence, actor, action, reason,
  revision, timestamp, before/after/previous/event hashes. They do not contain document content or
  the full action envelope.

## Migration and rollback

- Migration is transactional and additive: create/check `audit_schema` version 1, then create
  `audit_heads`, `audit_events`, and the no-update/no-delete triggers. Reopening is idempotent and
  unrelated tables plus `PRAGMA user_version` are proven unchanged.
- Rollback of an application release leaves the `audit_` tables and immutable events in place; it
  does not run a destructive down migration. A database-level rollback requires a pre-migration
  backup/restore and the applicable human retention approval, so it was not performed here.

## Acceptance evidence

- Closing and reopening multiple store instances preserves the first export snapshot identity and
  both immutable audit revisions after the current result changes.
- Two actors racing from separate SQLite connections with the same HEAD produce one committed
  sequence and one `AuditConflict`.
- A connection-scoped append followed by caller rollback leaves neither event nor HEAD.
- Exact tenant/run predicates prevent cross-tenant reads. Update triggers reject overwritten
  events, and a deliberately disabled trigger followed by row tampering is detected by complete
  hash-chain verification.
- The schema test asserts the exact audit-event columns, including both revision and all required
  hashes, and proves no document-content column exists.
- TASK-028 integration tests prove canonical events retain the same before/after hashes as the full
  action envelopes, idempotent replay adds no event, expiry permits a new revision, and an audit
  failure rolls back the action and idempotency writes.

## TDD record

1. Before implementation,
   `uv run --no-sync pytest tests/acceptance/test_audit.py tests/acceptance/test_jobs.py -q`
   exited 2 during collection with two
   `ModuleNotFoundError: No module named 'proofops.adapters.local.audit_store'` errors.
2. After the minimum SQLite adapter and job-transaction integration, the same command exited 0:
   `28 passed in 0.20s`.
3. Important review found that the connection-scoped API accepted autocommit connections. The new
   regression was run before the fix and exited 1 with `Failed: DID NOT RAISE ValueError`; an
   autocommit caller could otherwise persist EVENT before a later HEAD failure.
4. The adapter now rejects a connection without an active transaction before its first read/write.
   The regression and a `sqlite3.Row` schema-initialization check then passed: `2 passed in 0.05s`.
   The exact storage-column and DynamoDB one-event-put/one-HEAD-CAS assertions remain covered.

## Final exact commands and results

| Command | Actual result |
|---|---|
| `uv run --no-sync pytest tests/acceptance/test_audit.py -q` | exit 0, `7 passed in 0.05s` |
| `uv run --no-sync pytest tests/acceptance/test_audit.py tests/acceptance/test_jobs.py tests/acceptance/test_reproducibility.py tests/unit tests/contracts -q` | exit 0, `82 passed, 2 warnings in 1.68s`; warnings are existing FastAPI/Starlette deprecations |
| `uv run --no-sync ruff check packages/proofops/domain/audit.py packages/proofops/adapters/aws/audit.py packages/proofops/adapters/local/audit_store.py packages/proofops/adapters/local/job_store.py tests/acceptance/test_audit.py tests/acceptance/test_jobs.py` | exit 0, `All checks passed!` |
| `uv run --no-sync ruff format --check packages/proofops/domain/audit.py packages/proofops/adapters/aws/audit.py packages/proofops/adapters/local/audit_store.py packages/proofops/adapters/local/job_store.py tests/acceptance/test_audit.py tests/acceptance/test_jobs.py` | exit 0, `6 files already formatted` |
| `uv run --no-sync mypy packages/proofops/domain/audit.py packages/proofops/adapters/aws/audit.py packages/proofops/adapters/local/audit_store.py packages/proofops/adapters/local/job_store.py` | exit 0, `Success: no issues found in 4 source files` |
| `uv run --no-sync python scripts/verify_architecture.py` | exit 0, all purity, DTO, port, composition, and read-only contract checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task022-final.iTcmYb` | exit 0, sdist and wheel built |
| `git diff --check -- <owned TASK-022/TASK-028 integration files>` | exit 0, no diagnostics |
| `if rg -n '[[:blank:]]+$' <owned files>; then exit 1; else exit 0; fi` | exit 0, no trailing whitespace in the untracked task files |

No dependency or lock file changed. Tenant-isolation, parameterized SQL, immutable-row triggers,
tamper detection, and transaction failure injection are the focused security/integrity checks; no
real AWS service or product model was called.

## Remaining / not run

- The only remaining TASK-022 implementation is HTTP `GET /v1/runs/{run_id}/audit`; API router and
  composition files were outside this dispatch's ownership.
- Real DynamoDB calls, IAM enforcement, AWS mutation/deployment, product model calls, private
  customer processing, and human data/rights/legal gates are `not_run` or remain human-blocked as
  required. They are verification gates, not additional local adapter behavior claimed here.
