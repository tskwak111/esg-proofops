# Source-bound preliminary ensemble — 2026-09-19 KST

This is a local diagnostic CLI, not the production preliminary supplier or a
real-tagging worker activation. No service decision, grade, or confirmed tag was
published. Existing run snapshots and the USD20 shared ledger remain unchanged
except for the twelve explicitly authorized provider call records.

## Implementation and compatibility

`uv run python -m evaluation.preliminary_probe --state EXISTING_PILOT --output NEW_DIR`
prints the maximum call count without reading credentials or calling the model.
Append `--key-file /absolute/path/.env.upstage.local --invoke` to execute after
current source bytes and immutable extraction/native-source receipts are replayed.
Default model is solar-pro4, two verified claims, three independent calls per
claim, max1024 output tokens. `--max-claims` is1..20. Other source claims remain
unverified/deferred, never absent. All calls use the existing shared monetary ledger.

The CLI is an explicitly invoked evaluation under the user's existing permission;
its authorization text is an audit note, **not** a service preflight approval.
The function requires trusted caller-owned canonical graphs and the authorized
probe. It must not be exposed as an HTTP endpoint. Production source/settings
preflight, dual runtime snapshots and preliminary supplier publication remain open.

All selected claims validate before the first call. Exclusive operation-directory
creation blocks concurrent/restarted evaluation of that output path; there is no
resume/retry option. Requests, full provider replies and validation outcomes are
create-only, read-only files beneath a private directory. A provider failure stops
remaining calls and leaves any uncertain monetary reservation untouched. A new
output path is an explicitly new experiment, not idempotent recovery. These use
existing local receipt writes; power-loss fsync guarantees are not newly claimed.

Each request records tenant/source/graph/claim/prompt/model/rule identity and replica.
The three provider IDs must be distinct and all three validated classifications
(including exact dimension refs and optional field presence) must agree to show
`consistent_candidate`. That label measures repeatability only. Null tracks,
failed replies, replayed provider IDs and disagreements stay `needs_review`.
No majority is promoted to a grade. Confidence is retained but never used as an
approval threshold. Raw invalid replies remain inspectable.

No API/DB or dependency change. Existing preliminary validation accepts prior
responses. The updated semantic-role instructions change the prompt hash; old
receipts are preserved. Rollback: stop using this diagnostic CLI and restore the
prior prompt for new runs; retain all prior receipts and ledger records.

## Actual observations

Same two source-verified claims on KB physical page30, not a held-out gold set:

| Prompt | Calls / literal-schema valid | Tracks across replicas | Full candidate consistency |
|---|---:|---|---:|
| Prior prompt |6/6|management/goal/management; goal/management/management|0/2|
| Explicit predicate/entity/metric roles |6/6|management/management/management for both|1/2|

The second revised claim differs only in whether optional null dimensions are
explicitly emitted. The comparator deliberately keeps this as review-required;
omission is not treated as proof that a scope axis is inapplicable. No semantic
gold accuracy or generalization rate is available. Instructions were improved
using these development examples; these examples cannot be called holdouts.

Before: USD7.9372558150 committed/reserved,1380 rows,6 old unsettled.
This work:12 settled calls, USD0.004879380; no new unsettled calls.
After: USD7.9421351950 committed/reserved,1392 rows,6 old unsettled / USD20 cap.
Receipt file hashes, source/prompt hashes and per-experiment accounting are in
`preliminary-ensemble-20260919.json`; private full report text stays in `.local/`.

## Verification and external review

- Failing-first diagnostic tests:4 failures from missing evaluator, then pass.
- Whole suite before final key-error improvement:2291 passed,7 skipped,2 existing
  deprecation warnings (`/tmp/proofops-preliminary-ensemble-tests.txt`).
- Final focused suite:41 passed (9 diagnostic integration +32 source-bound
  preliminary acceptance), including failure-first missing-key validation.
- Ruff check/format, mypy176 source files, architecture, package822 checks,
  four Python package builds, web typecheck/build and source/license gate passed.
- Browser/cloud deployment E2E and new vulnerability network audit:not_run.
  Existing staging-gate E2E tests were included in the whole Python suite.
- Orca run `run_accf87be2854`: Muse Spark1.3 reviewed real-tagging contracts;
  Muse Spark1.2 reviewed evaluator and ran focused tests. The missing-key error
  was reproduced and fixed before source replay. Both workers released/closed.

## Remaining service blockers

Real tagger worker/API activation still needs independent extractor/tagger runtime
snapshots, a reviewed provider-token reservation composition, durable authorized
preliminary/relationship suppliers and verified broader evidence retrieval.
This evaluator makes those changes measurable; it does not silently enable them.
Domain GAP-001..010, semantic gold/holdout evaluation, and table/footnote coverage
remain unresolved. No production-readiness or accuracy claim follows from passing
software tests or these twelve validly quoted model replies.
