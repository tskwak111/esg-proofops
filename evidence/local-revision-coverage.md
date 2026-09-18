# Local revision coverage repair

Date: 2026-09-09 (Asia/Seoul). Scope: local synthetic SQLite only.
Base accepted implementation: `8be891a`; other workers' changes were retained.

## Contract and root cause

Read the Master, original v2 domain, chapters 26/27/28/31/19, task execution
order and TASK-019/020/026/027, with the following controlling evidence:

- Original v2 §§4.1, 4.3, 5.1 and 6: humans confirm tags, pure rules compute
  decisions, review state is separate from labels, and output distributions
  reflect decisions. No requirement freezes mutable run claim counters at tagging.
- Master §§5–6 and rule contract §6: review/rescore creates new immutable
  decision revisions and preserves original tags, prior decisions and reports.
- Rule contract §5: grade denominator contains only `decision_status=decided`;
  unresolved claims and incomplete source coverage remain visible.
- TASK-027 / FR-027 / AT-027: update coverage from job/source/claim counters;
  budget-limited work remains partial, without a complete badge.
- API §4 and the error handling contract: compare review/tag revisions, retain blocked
  decisions, and roll back result writes when the audit transaction fails.

`LocalSQLiteReviewStore.resolve` and `LocalSQLiteRescoreStore.commit` advance
`claim_head` then call `_bump_run`, which previously changed only revision/epoch.
The mutable run therefore kept its original tag-checkpoint claim counts.
`tag_runner` and `validate_tag_commit` define `claims_needs_review` as processed
checkpoint claim records minus decided records, including blocked records that
have no published claim head. Counting only heads would silently lose those rows.

Caller trace: `_bump_run` is used by job lease acquisition, job commit, failure,
retry, cancellation, standalone initial review publication, review resolution,
and rescore commit. Refresh is enabled only on the last two mutation paths.
`ReviewService.resolve_review` supplies the trusted builder to `resolve`;
`RescoreService.create_rescore` prepares decisions for `commit`. Stage publication,
standalone review publication and existing lifecycle calls keep their behavior.

## Change and compatibility

The existing shared `_bump_run` accepts an optional claim-count refresh. A single
SQL aggregate joins current heads to their exact immutable decision revisions
within both tenant and run scope. It reads the decision status in SQLite and
returns one count; it does not reload tags, original packets, model receipts,
checkpoints or full rescore artifacts for this refresh.

Only the two existing claim counters change. Their processed total is preserved:
`claims_needs_review = previous(decided + needs_review) - current decided`.
A count exceeding the recorded processed total fails closed. Unknown/conflict,
missing heads and unreadable/unprocessed work are not converted into absence or
new completion. Pages, chunks, discovery count, scope, `complete`, run status and
current stage remain unchanged. Existing transactions include refresh, head
updates, audit append and idempotency; stale checks precede mutation.

No API fields, database schema, migration, dependency, lockfile or domain rule
changed. Existing readers use the same coverage fields; old standalone fixtures
without coverage retain that absence. Rollback is code-only with writers stopped;
retain all SQLite rows and immutable revisions. No historical reports or
checkpoints are rewritten, and existing stale runs refresh on their next
successful review/rescore rather than receiving an unaudited backfill.

## Failed-first evidence and verification

The new regression uses the existing synthetic verified parse/extract/tag fixture,
real SQLite transactions, pure `evaluate` / `create_rescore`, and authenticated
GET run/summary endpoints with JSONSchema validation. Its trusted store-boundary
review builder supplies explicitly synthetic confirmed facts; this is not a
claim of end-to-end human evidence verification. Existing acceptance suites
exercise the actual review/rescore HTTP guards. No engine output is mocked.

1. Before the shared fix, `uv run pytest tests/integration/test_revision_coverage.py
   -q -x` failed on review: GET run returned `claims_decided=0` after real E3
   evaluation, expected `1`. Initial fixture source-verification errors were
   corrected before accepting this failure as the regression signal.
2. With review fixed and rescore still using its original `_bump_run` call,
   `uv run pytest tests/integration/test_revision_coverage.py -q -k
   'current_counts and rescore'` failed: GET run kept `1` after a real
   `blocked_rule_gap` rescore, expected `0`.
3. Final `uv run pytest tests/integration/test_revision_coverage.py -q`:
   **9 passed**, two existing Starlette/httpx/AnyIO deprecation warnings.
   Includes both transitions, stale CAS, failed audit rollback (job records,
   audit events and audit heads unchanged), foreign mutation/read denial,
   same-ID foreign tenant/run aggregate isolation, and partial/unheaded/
   unreadable/unprocessed coverage preservation. Original checkpoint remains
   byte-identical; old unknown tag and E3 decision revisions remain retained;
   synthetic transport call count remains three.
4. `uv run pytest tests/acceptance/test_reviews.py tests/acceptance/test_rescore.py
   tests/acceptance/test_jobs.py tests/integration/test_local_tag_runner.py -q`:
   **111 passed**, the same two deprecation warnings.
5. Scoped `uv run ruff check` and `uv run ruff format --check` for the three
   changed adapters and new integration test: passed.
6. `uv run mypy packages/proofops/adapters/local/job_store.py
   packages/proofops/adapters/local/review_store.py
   packages/proofops/adapters/local/rescore_store.py`: passed, three source files.

The cross-pack GET summary test also exercises the summary worker's separately
owned `summary_store.py` lineage fix (`ctx_e575943c939c`). Before that fix it
returned 409; the final test passes with immutable rescore tag/input pins intact.

Not run: live models, AWS, customer PDFs, full WIP suite, deployment and full-app
build/E2E. These are outside the dispatched scoped adapter repair; no production
completion or measured accuracy claim is made. Git commit/push remains root-owned.

Coordinator acceptance: `uv run pytest tests/integration/test_revision_coverage.py -q --tb=short` passed **9 tests**, with two existing dependency deprecations. The shared SQL and both callers were reviewed; no schema or immutable checkpoint rewrite.
