# TASK-028 — durable jobs evidence

## Approved implementation and storage contract (before implementation)

Scope: existing TASK-028 design, plus coordinator-authorized
`packages/proofops/application/ports/jobs.py` and
`packages/proofops/adapters/local/job_store.py`. Implement actual local SQLite
transactions and immutable checkpoint bytes, with queue identities and leases in
the application port. Consumer and relay depend on that port. No new dependency.

Local schema v1 adds `job_schema` and `job_records` only; the latter
has `(tenant_id, run_id, kind, record_id)` primary key and a BLOB value. Serialized
run/job/outbox/idempotency/usage records and immutable artifact bytes commit in one
`BEGIN IMMEDIATE` transaction. Reopen uses existing rows; unknown schema version
fails closed. There is no production DynamoDB/API contract migration in this task.
Rollback: stop local workers and retain the database/checkpoints, then revert the
local code; do not delete records or downgrade a newer schema. This adapter is
explicitly local-synthetic-only, is not automatically selected by composition,
and is not an AWS distributed implementation.

Plan: acceptance failure → typed port/local durable repository → consumer and
outbox relay → focused acceptance/lint/type/contracts/unit/build/security checks.
Cancel/retry use caller-authorized tenant/run, revision CAS and idempotency key;
successful checkpoint bytes remain immutable. The coordinator owns HTTP wiring,
shared contracts, main/composition, and Git.

## Red test

`uv run pytest tests/acceptance/test_jobs.py -q`: exit 2, expected
`ModuleNotFoundError: No module named 'proofops.adapters.aws.jobs'` during collection.
Tests use synthetic bytes/identities and real file-backed SQLite connections.

## Implemented and verified behavior

- `JobMessage` binds tenant/run/document version/job UUIDs, stage/shard and the
  immutable input hash. The caller must construct that input hash from its frozen
  source/model/prompt/rule/replica inputs; jobs preserve it without inventing them.
- `claim_job` atomically claims pending/due or expired work, increments a monotonic
  fence and attempt, and persists an immutable lease identity. A competing process
  or connection cannot claim a live lease. Heartbeat cannot revive expired work.
- `commit_job` checks tenant, full message identity, owner, fence, attempt, live
  expiry and cancellation in one transaction. Checkpoint bytes are immutable at
  `job/{job_id}/attempt/{fence}/checkpoint`; their SHA-256 is verified on reads.
  Checkpoint, next job and next outbox commit together or all roll back.
- Cancel prevents subsequent operation calls and publication of late results.
  In-flight success and classified failures preserve immutable usage per attempt,
  including after cancellation or lease loss. Jobs never generate E grades,
  labels, source refs, or evidence absence from processing errors.
- Transient `MODEL_THROTTLED`, `PROVIDER_5XX`, `MODEL_TIMEOUT` use up to three total
  attempts per retry cycle with injected full jitter, 2/4-second retry windows,
  and provider Retry-After capped at 60 seconds. Other failures are retained and
  not automatically retried. More than five SQS receives terminally fails the
  local job; actual SQS redrive/DLQ configuration remains not_run.
- Manual retry resumes failed jobs, resets that explicit retry cycle, and preserves
  all successful checkpoints and monotonically increasing fences/attempts.
  Cancelled runs cannot be silently revived by retry. Both operations enforce
  revision CAS, reason and an idempotency key; a key replays for 24 hours, then
  a new mutation must pass the current revision check.
- Both actions now require the server-resolved `actor_sub` and injected `now`.
  Full immutable action envelopes retain tenant/run/target/event UUID, actor, UTC
  timestamp, reason, before/after run+job snapshots and their hashes in the same
  transaction. An expired idempotency key can be reused without overwriting the
  earlier action envelope. This is not yet the canonical TASK-022 audit chain.
- Outbox transport failure retains durable pending events. Delivery accepted just
  before a simulated transport error replays the same event identity after reopen.
  The consumer executes only once. Busy deliveries return `deferred`, so a future
  SQS caller must retain/redelay them until lease recovery rather than acknowledge
  and destroy the sole retry opportunity. Only committed/ignored deliveries are
  unconditionally safe to acknowledge; other dispositions require state handling.

## Additional red/green evidence

- Classified consumer failure test: `uv run --no-sync pytest
  tests/acceptance/test_jobs.py -q` initially exited 1 with `1 failed, 16 passed`
  because `StageFailure` was missing; implementation passed all 17 cases.
- Busy-message regression: the same command exited 1 with `1 failed, 17 passed`
  (`ignored` instead of `deferred`); the shared consumer now returns `deferred`
  for pending/leased work and the regression passed.
- Coordinator review regression: the same command exited 1 with `1 failed,
  20 passed` because `cancel_run` did not accept actor identity. Required actor/time,
  immutable before/after action records and 24-hour idempotency expiry now pass.
  Existing tests gained the required actor/time inputs without weakening assertions.
- Early Ruff runs found E501/I001 and E731; formatting/import ordering and the
  assigned test lambda were corrected. Final commands below passed.

## Final verification (2026-09-09 Asia/Seoul)

| Exact command | Actual result |
|---|---|
| `uv run --no-sync pytest tests/acceptance/test_jobs.py -q` | exit 0; `21 passed in 0.17s` |
| `uv run --no-sync pytest tests/acceptance/test_jobs.py tests/acceptance/test_reproducibility.py tests/contracts/test_package_contracts.py tests/unit -q` | exit 0; 74 passed; two existing FastAPI/Starlette deprecation warnings |
| `uv run --no-sync ruff check packages/proofops/application/ports/jobs.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/jobs.py apps/worker/src/proofops_worker/consumer.py apps/worker/src/proofops_worker/relay.py tests/acceptance/test_jobs.py` | exit 0; `All checks passed!` |
| `uv run --no-sync ruff format --check packages/proofops/application/ports/jobs.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/jobs.py apps/worker/src/proofops_worker/consumer.py apps/worker/src/proofops_worker/relay.py tests/acceptance/test_jobs.py` | exit 0; `6 files already formatted` |
| `uv run --no-sync mypy packages/proofops/application/ports/jobs.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/jobs.py apps/worker/src/proofops_worker/consumer.py apps/worker/src/proofops_worker/relay.py tests/acceptance/test_jobs.py` | exit 0; `Success: no issues found in 6 source files` |
| `uv run --no-sync python scripts/verify_architecture.py` | exit 0; domain purity, fixed tag schema, composition fail-closed checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task028-build` | exit 0; source distribution and wheel built |
| `uv build --package proofops-worker --out-dir /tmp/proofops-task028-build` | exit 0; source distribution and wheel built |
| `git diff --check -- apps/worker/src/proofops_worker/consumer.py apps/worker/src/proofops_worker/relay.py packages/proofops/application/ports/jobs.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/aws/jobs.py tests/acceptance/test_jobs.py evidence/task-028.md` | exit 0; no whitespace errors |

The 21 acceptance cases include actual separate-process commit/reopen, eight
competing SQLite connections, actual transaction rollback after checkpoint write,
local relay→consumer→persisted-byte end-to-end flow, tampering/tenant-isolation
security checks (including identical UUIDs in two tenants), checkpoint corruption,
immutable usage, component schema coexistence, and refusing a newer schema.
No mocks replace the repository or consumer. Unit/document-contract validation
is reported separately from real local behavior; the document validator is not
claimed as an app test.

## Integration handoff and not_run gates

- `LocalSQLiteJobStore(path)` is deliberately local-synthetic-only. Tables are
  `job_schema` and `job_records`; no global `PRAGMA user_version` is changed.
  The local caller may use the shared configured `LOCAL_DATABASE_PATH`, but this
  task did not change composition or environment selection. Never select it for
  staging/production based on this local evidence.
- Public worker port lives in `application/ports/jobs.py`; consumer functions
  take `JobRepository`. Local repository methods include `create_run`, `enqueue`,
  `claim_job`, `heartbeat`, `commit_job`, `fail_job`, `cancel_run`, `retry_run`,
  `get_run`, `get_job`, `read_checkpoint`, `get_usage`, `get_action` and outbox APIs.
  `cancel_run(tenant_id, run_id, *, expected_revision, idempotency_key, reason,
  actor_sub, now)` and `retry_run` with the same arguments return internal local
  state, not the public Run DTO. The HTTP layer must authorize editor membership,
  resolve actor from session, enforce CSRF/origin, and serialize the approved DTO.
- HTTP cancel/retry routing, main/composition wiring, canonical TASK-022 audit
  HEAD/event chain integration, production run counter release, pipeline-level
  final run completion and actual SQS ack/redrive: not_run in this bounded task.
  Current TASK-022 adapter only exposes a DynamoDB audit transaction boundary;
  full local action envelopes are retained for coordinated integration. They
  are not represented as a completed canonical audit chain.
- Real DynamoDB/S3/SQS, distributed Fargate recovery, real model calls, AWS changes,
  browser E2E, private customer data, legal/data-rights and other human-only gates:
  not_run. No fabricated AWS resources, model ARN, regulatory facts or accuracy
  figures. Checkpoint payloads and the transport failure are explicitly synthetic.
- No new dependency, no shared contract/API/main/auth/manifest edits, no commit or
  push. Coordinator owns integration and Git.
