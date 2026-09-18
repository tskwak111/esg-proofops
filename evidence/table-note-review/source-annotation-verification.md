# Original-backed citation and classification revisions

The new `/v1/runs/{run_id}/source-condition-review/revisions` operation records
citations and note/not_note/unknown/conflict classifications. It requires a reviewer,
CSRF/Origin, quoted If-Match, an idempotency key and strict bounded factual input.
Ownership/conditions/claim bindings are rejected unless empty; numeric receipts remain
empty and coverage unknown. No source graph, claim tag, grade or label is promoted.

Before a new confirmed citation or note/not_note classification is saved, the server
replays its original display against the pinned fragment and base review revision.
Recomputing the hash of a forged image receipt does not bypass this comparison.
Replays occur outside the write lock, followed by epoch/source/revision checks inside
the transaction. Source-view receipts are content-addressed, deduplicated and stored
atomically with the revision, audit, idempotency response and head/epoch update.
Omitted factual entries remain in the effective state; old revisions remain unchanged.

Exact authenticated retries retrieve the first immutable response before re-rendering
originals. The acceptance test repeats a revision-1 request after later revisions while
original loading is deliberately unavailable, and still receives the original revision-2
response. Changed-key payloads, forged receipts and submitted grades are rejected.
Injected audit failure rolls back both the new receipt and revision; the same key can
then retry. An injected run change before resolve leaves no receipt/idempotency write
and returns 412; retry succeeds. Viewer, foreign tenant and anonymous cached-retry
requests remain 403/404/401. The test advances its clock for a new rate window without
disabling rate enforcement.

Real-report exercise through the full local API used local synthetic reviewer sessions
and this agent's visual checks of the previously rendered originals, **not an independent
human/domain-expert validation**:

| Report/page | Recorded facts | Result |
|---|---|---|
| Samsung Electronics/72 | External note classification; citation stays unknown because NF₃ native subscript ordering is split | revision 2; unknown coverage; no numeric result |
| LG Chem/97 | External biomass-note classification and original-text confirmation | revision 2; unknown coverage; no numeric result |

Both exact retries matched, revision-1 GET remained identical, and the original issues
remained unchanged. Private requests/responses: `.local/note-review-integration/source-annotation-api-v1/`.
Samsung revision SHA256: `ea2985716376f167a41eb3b14d7a68af569adc4c01cbcaf021e731a87cc790f2`.
LG Chem revision SHA256: `7a5ff08a652abb37347acb5bc0e91b387597c4561d3829ab842ff00fcdf2a642`.
Zero external model calls; the shared USD10 ledger was not modified by this work.

Orca contract task `task_bc4b94c3eb23` / `ctx_0145f5759cad` added the operation and four
DTO-derived models to the two contract catalogs, preserving all old paths/models.
Read-only review `task_cc6adf39fe08` / `ctx_a2852220ca55` passed seven focused tests
and a temporary resolve-epoch/auth repro. No runtime defect was reproduced; stale
implementation-status prose was corrected, and its suggested regression cases were
added. Both workers settled and were released/acknowledged.

Verification: focused API/store tests passed; Ruff lint/format passed (287 files), CI
mypy passed (170 files), architecture checks passed and all four Python packages built.
Document/contract validation passed 782 checks (49 operations); not an accuracy metric.
Isolated wheel replay reopened 18 actual worker checkpoints with unchanged graph hashes
and zero model calls. Final full suite: **1917 passed, 2 warnings in 139.85s**;
log: `.local/note-review-integration/source-annotation-final-full.log`.

Remaining service work: ownership and supported condition validation, effective-source
coverage, numeric checker/receipt integration, shared approved-view consumers and browser
review UX/E2E. Source confirmation alone does not solve these or interpret arbitrary
geographic/measurement prose. No service-complete or corpus-accuracy claim is made.
