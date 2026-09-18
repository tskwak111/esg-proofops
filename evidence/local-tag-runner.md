# Local tag-stage worker integration

Dispatch: `task_fe54eab1bb24` / `ctx_699532a3fe76`.
Result: implemented local tagging delivery and verified the scoped integration.
This is not a production validation, model approval, or verified-parser claim.

Coordinator acceptance: the actual local tag runner, tagging, review and job
suites passed together: `uv run pytest tests/integration/test_local_tag_runner.py
tests/acceptance/test_tagging.py tests/acceptance/test_reviews.py
tests/acceptance/test_jobs.py -q` — 118 passed, two existing dependency warnings.
An initial command used nonexistent `test_job_lifecycle.py` and ran no tests;
the corrected command above is the acceptance result. Worker ctx_699532a3fe76
was released before acknowledgement; no actual model call was authorized or run.

## Implemented path

`LocalTagRunner.run_once(tenant_id=..., run_id=...)` consumes only the selected
run's existing tag outbox message. It loads the frozen run snapshot, original
source via `load_run_graph`, and replay-validated extraction via `LocalClaimStore`.
It retains source/object/version/manifest/graph/parser/extraction/rule/runtime and
settings pins, and requires the exact frozen `TaggingSettings` hash and runtime
identity before any synthetic tagging request.

Source quality remains authoritative. An actual parser's unverified source stays
`fast_preview`, `vision_status=not_run`, with blocked claim records containing no
`TagRun`, provider response, usage or decision fabricated for a nonexistent call.
Missing runtime or preliminary classification is likewise gated. A blocked
checkpoint makes the run `partial`; it consumes its outbox rather than leaving a
misleading endless running stage. Coverage never changes unknown to absent and
never declares full completeness in this local stage.

For an explicitly supplied synthetic transport and source-backed preliminary
classification, the worker calls actual `retrieve_evidence`, then
`freeze_track_packet` once per claim before all three calls, then actual
`tag_replicates` and `form_consensus`. It calls the pure domain `evaluate` only
when consensus supplies `ConfirmedTags`. P4/P6 and unknown applicability are not
suppressed. The built-in local transport emits every selected element as unknown;
it never infers a missing track or invents evidence/grades.

The original retrieval packet, selected packet, full raw and guarded receipts,
usage, replica identities, model/prompt/rule/graph hashes, consensus, context,
relation tags and optional Python decision are retained in the immutable tag
checkpoint/review input envelope. The rich original graph is loaded and verified
from its existing parser artifact; ReviewInputs retains its full graph digest
and identities, per the review worker's stable format.

## Atomic publication and recovery

- A minimal optional `publish` hook in `LocalSQLiteJobStore.commit_job` is
  restricted to local tag checkpoints backed by a committed extraction. The
  same SQLite transaction validates source/extraction/snapshot pins and coverage,
  owns the current lease/cancellation fence, writes the checkpoint, invokes
  `ReviewService.publish_transaction`, consumes the outbox, publishes run/claim/
  review heads and initial revisions, appends audit events and bumps the run
  mutation epoch once. An exception rolls the entire publication back.
- Initial tag/decision/review revisions use the review worker's existing
  `LocalSQLiteReviewStore`. No parallel revision store was introduced.
- The new `SQLiteImmutableCacheClient` implements the existing immutable cache
  client interface with file-backed conditional writes. Exact raw-response
  recovery survives a new cache client and worker process; keys retain the
  existing tenant/consent/document/role/replica/request/epoch boundary.
- Stable per-claim ensemble IDs derive from the immutable tag job ID. Existing
  SQLite budget/usage reservations and dispatch markers prevent duplicate calls
  or billing. The worker checks/heartbeats its lease before reservations and
  calls. A fence signal escapes the provider-error boundary without fabricating
  a failed provider response when the transport was never invoked.
- Actual in-flight usage and raw cache artifacts survive cancellation/stale
  leases, while stale workers cannot publish heads or checkpoints. A lease retry
  recovers completed receipts and invokes only missing independent replicas.
- A failure followed by a crash before transport acknowledgement is recovered
  by acknowledging the terminal delivery without repeating work.

## Stable integration interfaces

```python
LocalTagRunner(
    store, uploads, parser, *, telemetry,
    transport=None, preliminary=None, clock=time.time,
)
runner.run_once(tenant_id=tenant_id, run_id=run_id)

# Explicit local transport: SyntheticTaggingTransport().
# Its token_counter is an explicitly synthetic byte counter, not model tokenization.
# Preliminary input is a caller-owned function:
# preliminary(claim, graph) -> (TrackCandidate, ClaimContext, relation_tags)
# No function / missing runtime means blocked, never guessed classification.

LocalTagStore(store, uploads, parser).load_snapshot(tenant_id, run_id)
LocalTagStore(store, uploads, parser).load_inputs(tenant_id, run_id, claim_id)
# load_inputs -> ReviewInputs; validates original sources/extraction, reconstructs
# typed receipts, recomputes consensus and optional Python decision, and verifies
# the full retained snapshot digest without any transport invocation.

ReviewService(
    LocalSQLiteReviewStore(store.jobs),
    load_inputs=LocalTagStore(store, uploads, parser).load_inputs,
)
# Worker invokes publish_transaction(connection, inputs) inside the same fence.
```

Durable stage outcomes: `blocked`, `needs_review`, `completed` (the tag stage only;
run coverage remains partial). Delivery outcomes: `cancelled`, `discarded`,
`deferred`, `failed`, `ignored`, `idle`. `local_tag_checkpoint_v1` plus
`run.tag_job`, `tag_snapshot_sha256`, `tag_stage_status`, `coverage` and the
existing immutable artifact reference describe the persisted stage state.

CLI:

```sh
uv run python -m proofops_worker.main --tenant-id TENANT_UUID --run-id RUN_UUID --once --stage tag
```

Only `LOCAL_TAGGING_MODE=local_synthetic` wires `SyntheticTaggingTransport` in
worker composition. Without it the runner has no transport and remains gated.
Preliminary classification is deliberately not guessed by CLI composition; it
requires an explicit caller-owned source-backed tagging input. Existing parser
profile/database settings and source APIs are reused.

Coordination: early status messages `msg_4adf86270e8e` and `msg_eb06651a7255`;
review hook requested in `msg_02d3f6cd9cfa` / `msg_92f80a672421`, confirmed by root
in `msg_a7abd455dc2f`, integration results sent to review worker in
`msg_f5989c2e2e56`. Full `orca orchestration check --json` messages were consumed,
including the exact review transaction contract, before completion.

## What the tests prove

1. **Actual generated PDF path:** HTTP upload, actual OpenDataLoader/pdfplumber
   parsing, extraction, tag gate and CLI. It proves unverified actual parsing
   stays fast_preview and creates no tagging receipts, grades or model usage;
   run status becomes partial with a durable blocked checkpoint.
2. **Separate explicit synthetic verified fixture:** `SyntheticVerifiedParser`
   reads text from the generated PDF, persists its own manifest and produces a
   clearly marked synthetic verified paragraph. It does not promote or replace
   the actual parser in the preceding test. This bounded fixture proves the
   real downstream retrieval/full-catalog freeze/tagging/consensus/cache/budget/
   review-storage path with three distinct invocations and full raw provenance.
   All synthetic tags stay unknown and initial decision remains absent.
3. **Real failure injection:** crash after review heads/audit, cancellation before
   and during a call, expired lease, malformed checkpoint pins/coverage, source/
   settings/tenant mismatch, and failure-before-acknowledgement. It proves atomic
   rollback and source/fence checks; durable reopen recovers raw responses with
   exactly three total dispatched attempts, no duplicate charges/revisions.
4. **Existing scoped regressions:** tagger acceptance and durable job tests cover
   replica isolation, cache identity, strict structured-output contracts, budget,
   malformed-provider preservation and job lease behavior.

No test replaced citation, binding, hashing, tagging, consensus, budget, review
publication or cache recovery with mock success results. Synthetic parser and
transport fixtures are explicit; monkeypatches inject faults or configure test
inputs. Human-only source/data/model/legal approvals remain unperformed.

## Exact verification commands and results

Initial failing-first command:

```sh
uv run pytest tests/integration/test_local_tag_runner.py -q
```

Exit 1: **3 failed in 0.16s** because the tag runner/cache client were missing.
After implementation the same command passed **3 tests in 2.19s** with two
existing dependency deprecation warnings.

Targeted development commands:

```sh
uv run pytest tests/integration/test_local_tag_runner.py -q -k verified_synthetic
uv run pytest tests/integration/test_local_tag_runner.py -q -k 'fence or tamper or preliminary'
uv run pytest tests/integration/test_local_tag_runner.py -q -k 'cli or pins_fail'
```

- The verified-fixture command initially failed its synthetic RulePack approval
  setup; adding explicit synthetic fixture approval metadata allowed the same
  actual activation API to run. It then passed **1 test, 3 deselected in 0.55s**.
- Fence/tamper/preliminary: **9 passed, 4 deselected in 1.90s**.
- CLI/pins: **3 passed, 1 failed, 13 deselected in 1.88s**. The failure was an
  incorrect expected exception type: foreign access correctly raised the existing
  `RunRejected(RESOURCE_NOT_FOUND, 404)`, not KeyError. The test now checks that
  precise existing contract; no production behavior was changed for it.

Formatting/lint commands (same exact file scope was used throughout):

```sh
uv run ruff check apps/worker/src/proofops_worker/tag_runner.py apps/worker/src/proofops_worker/main.py apps/worker/src/proofops_worker/composition.py packages/proofops/adapters/local/tag_store.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/local/tag_cache.py apps/agent/src/proofops_agent/synthetic_tagging.py tests/integration/test_local_tag_runner.py --fix
uv run ruff format apps/worker/src/proofops_worker/tag_runner.py apps/worker/src/proofops_worker/main.py apps/worker/src/proofops_worker/composition.py packages/proofops/adapters/local/tag_store.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/local/tag_cache.py apps/agent/src/proofops_agent/synthetic_tagging.py tests/integration/test_local_tag_runner.py
```

Initial lint found 37 import/line-length findings (4 fixed), followed by formatting
7 files. Two later test line-length findings were formatted. Final lint is clean.

Final review discovered and reproduced the failure-before-acknowledgement bug:

```sh
uv run pytest tests/integration/test_local_tag_runner.py -q -k failed_delivery_recovery
```

Exit 1: **1 failed, 17 deselected in 0.55s**, showing the terminal delivery left
its outbox pending. The runner now acknowledges that delivery without work.
This new failure justified repeating the following small related regression
scope; no whole-workspace/500-test suite was run.

```sh
uv run pytest tests/integration/test_local_tag_runner.py tests/acceptance/test_tagging.py tests/acceptance/test_jobs.py -q
uv run mypy apps/worker/src/proofops_worker/tag_runner.py apps/worker/src/proofops_worker/main.py apps/worker/src/proofops_worker/composition.py packages/proofops/adapters/local/tag_store.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/local/tag_cache.py apps/agent/src/proofops_agent/synthetic_tagging.py
uv run ruff check apps/worker/src/proofops_worker/tag_runner.py apps/worker/src/proofops_worker/main.py apps/worker/src/proofops_worker/composition.py packages/proofops/adapters/local/tag_store.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/local/tag_cache.py apps/agent/src/proofops_agent/synthetic_tagging.py tests/integration/test_local_tag_runner.py
uv run ruff format --check apps/worker/src/proofops_worker/tag_runner.py apps/worker/src/proofops_worker/main.py apps/worker/src/proofops_worker/composition.py packages/proofops/adapters/local/tag_store.py packages/proofops/adapters/local/job_store.py packages/proofops/adapters/local/tag_cache.py apps/agent/src/proofops_agent/synthetic_tagging.py tests/integration/test_local_tag_runner.py
```

Final results: **89 passed, 2 warnings in 7.14s**; **mypy clean in 7 source
files**; **all lint checks passed**; **8 files formatted**. Before the final new
regression this scope passed 88 tests. Warnings are existing Starlette/httpx and
AnyIO deprecations, not application failures.

Scoped builds:

```sh
uv build --package proofops --out-dir /tmp/proofops-local-tag-runner-dist
uv build --package proofops-worker --out-dir /tmp/proofops-local-tag-runner-dist
uv build --package proofops-agent --out-dir /tmp/proofops-local-tag-runner-dist
```

All exit 0 and produced wheel/sdist. Worker was rebuilt after the final outbox
repair; the other package code did not change after their successful builds.

## Storage compatibility and remaining gates

Additive private SQLite `local_tag_cache_v1` stores immutable keyed payloads and
checksums; existing cache APIs verify payload hashes. Tag checkpoints reuse
existing `job_records` artifacts and pointers. No shared DTO/DB/API contracts,
manifest, migration owned by another worker, or existing revision was rewritten.
Older parser/extractor callers omit the optional commit hook unchanged. Rollback
stops tag writers and retains database/cache/checkpoint/review artifacts; do not
delete historical rows or rerun older code against a progressed stage blindly.

**not_run/blocked:** live product models, AWS/customer PDFs, source verification
approvals, rights/data/legal/model approval, production tokenization/pricing,
vision, real-cloud cache revocation/manifests, browser product E2E, deployment and
production accuracy. The local cache has durable immutable payload recovery;
distributed/cloud revocation is not claimed. Complete actual source validation
and explicit preliminary tags remain upstream gates. Coordinator owns API
composition/DTO/contracts, Git, and release integration; no commits, pushes,
subagents, new dependencies, or cross-owned file edits were made.
