# Automatic note worker contract — 2026-09-14

LocalParserRunner accepts an explicit caller-owned note_client. CLI opt-in is
--review-table-notes on parse only, mutually exclusive with supplied artifacts.
Composition uses the existing shared USD10 ledger and UPSTAGE_API_KEY, never a new
allowance. No public HTTP or database-column changes.

Before parsing/calls, an immutable parser_note_policy job_record pins automatic
mode, model identifier, extractor hash and batch hash under the active lease.
Disabled mode is also bound for new deliveries. Switching policy requires a new
run. A retry with no client can restore already-bound complete artifacts using the
stored policy; an incomplete automatic attempt cannot downgrade to disabled mode.

Automatic publication uses local_parser_checkpoint_v3, including policy SHA256,
full derived graph SHA256 and runtime artifacts (empty only if no tables exist).
Manual v1/v2 remain unchanged. The transaction checks policy/input binding, and
the common source reader checks exact all-table coverage and one artifact per page.
Readers/writers must deploy together; rollback retains a v3-aware reader or blocks
v3 runs. Never strip policy or downgrade published checkpoints.

Before each request the runner renews/checks its lease, then stores the request ID
in a tenant/run/job-scoped immutable registry. A stop/cancel/lease loss prevents
subsequent calls. Batch results live in a private path under the run's prepared
artifact scope and survive retries. The original parser graph remains unchanged.

Usage reads only registered request IDs from the existing ledger; missing
preflight reservations cost zero, unsettled reservations remain unknown. On retry,
unreported IDs are reconciled; recorded IDs are excluded, with atomic duplicate-ID
rejection when usage is published. Stale workers cannot charge an ID twice.
Unknown accounting prevents source publication and stays explicitly unknown.
An interrupted HTTP call may require review; no automatic transport retry occurs.

Review correction: request registration is not proof that the provider invocation
has returned. An immutable return marker tied to the registering owner/fence
separates terminal preflight rejection from a request still entering transport.
Only settled requests and returned requests without a reservation are finalized
in additive usage. Pending IDs/reservations are recorded as non-additive
observations, remain reconcilable, and block publication. A later immutable usage
entry may finalize them without editing old entries. Existing cost response fields
also include automatic note calls; pending observations cease making cost unknown
only when their exact IDs have been finalized. No schema/column migration is needed;
older readers must not consume these new automatic runs during rollback.

## Validation and remaining service boundary

Orca OpenCode Muse 1.3 Free accounting editor was interrupted after an explicit
free-quota-exhausted screen (ctx_7cbcbb98a987); unfinished edits were reviewed and
completed by root. Codex read-only review ctx_87cfb580ce72 reproduced two accounting
faults (unsettled publication and takeover before reservation). Failing regressions
were added before fixes. Second review ctx_ddae1832a0fc reproduced no remaining
high/medium defect in these paths; both Codex terminals were released. Agent review
is not human domain approval or production certification.

`uv run pytest -q`: 1891 passed, two existing dependency deprecation warnings,
144.05 seconds. Log: `.local/note-review-integration/pytest-automatic-worker-v1.log`.
This full-suite collection preceded three additional CLI tests and the no-table
case; their final targeted result is recorded separately. Ruff lint/format, CI
mypy (167 source files), all four workspace package builds and 759 document/contract
checks passed. Four pre-existing Ruff line-wrap deviations were formatted without
behavior changes. Bare `uv build` was the wrong command for this workspace and
failed package discovery; the supported `uv build --all-packages` passed.

Actual worker CLI validation is recorded in `automatic-worker-live.json` and private
`.local/note-review-integration/automatic-worker-live-v1/` archives. Kia p45 and Kakao
p114 produced three and six source-bound note proposals respectively, all still
association unknown / ineligible for scoring. Rendered original pages were inspected
by the agent. Replay preserved graph hashes with no extra calls. Two real requests
cost USD0.0024936450; cumulative ledger USD7.8090884350, 1336 calls, six pre-existing
unsettled reservations unchanged. Full report source bytes were retained locally;
only prepared text context was sent through the existing bounded transport.

Samsung Life p121 failed before a model call: two table blocks have unresolved
parser winners, so the shared layout reader rejects them before native note
preparation. This is a reproduced remaining service blocker, not a successful
third-report result. No source issue was suppressed and no conflicting table was
accepted. Next work must let unresolved table structure coexist with source-bound
page-note discovery while preserving all original conflict and scoring guards.
No deployment/AWS test or whole-corpus accuracy claim was made.

Final targeted automatic-worker suite: 12 passed, two dependency warnings, 7.10s
(`.local/note-review-integration/pytest-automatic-worker-targeted-final.log`).
An isolated `python -I` process reopened both real successful checkpoints from an
extracted wheel installation, blocked evaluation/scripts/tests imports, preserved
both graph hashes and made zero model calls. Receipt:
`.local/note-review-integration/automatic-worker-wheel-replay.json`. Direct zipimport
was not a valid check for the existing namespace-package directories; extracting
the built wheels reproduces installed-package behavior without changing dependencies.

Later changes: `unresolved-table-note-context.md` records the Samsung Life fix.
`page-note-coverage-contract.md` records the subsequent `automatic_pages_v2` policy,
which accounts for all selected pages even when neither parser recognizes a table.
The measurements above remain the original table-only run's historical results.
