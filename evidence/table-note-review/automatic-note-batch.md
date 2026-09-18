# Automatic all-table note preparation — 2026-09-14

`proofops.adapters.local.note_review_batch.review_tables` discovers every canonical
table in the supplied immutable graph and groups all same-page tables into one
request context. Its caller supplies the authorized transport and output directory;
the function creates no provider, credential or budget ledger. It returns the same
canonical runtime note artifacts accepted by the fenced parser input path.

Before calls, an exclusive new directory and immutable plan pin tenant, full graph
hash, selected table IDs/pages, model and helper/batch code hashes. Completed review
bundles are replayed against the original source, with exact full-table coverage
and artifact validation, without making new calls. A changed source, graph, model identifier,
pinned code hash, missing artifact or incomplete output directory rejects. Partial output is
not automatically retried because an interrupted call may already be charged.
The operator must retain old archives and resolve uncertain transport state before
starting a new authorized attempt. This is not a new approval mechanism.

A budget or transport stop code halts later model calls in the batch. Remaining
pages still get original-source packets and explicit not_run/unknown artifacts,
so they cannot disappear from numeric/retrieval/tagging holds. Empty detected notes
remain unknown. Completed cache means artifact preparation finished, never that
coverage or note ownership was approved. All issue states remain open on replay.

No HTTP/DB schema, run snapshot or previous revision changes. Existing parser
checkpoint v2 stores these returned artifacts unchanged. Old per-page extractor
archives stay readable; no validator/layout/extractor code is changed here.
Automatic worker composition and per-run live-provider configuration remain to be
connected; this function is the all-table preparation step, not a service-complete
claim. An incomplete batch prevents its caller receiving publishable artifacts.


The plan pins the model identifier and helper/batch source hashes, not arbitrary
transport configuration. Each runtime artifact additionally pins validator/layout
hashes. Source directories must be owned by the caller: mkdir sets 0700 on the
output leaf, not every existing ancestor. Preflight-rejected discovery requests
appear in request logs but are not billable model calls; do not report their count
as API usage. The injected Upstage-compatible transport owns that accounting.

The coordinator reproduced the reviewer's already-reviewed graph probe as failing
regression tests, then rejected any existing table_note_review issue before output
creation or client calls. This prevents silently stacking another batch over a
previous runtime view; use the exact original parser graph.

## Executed evidence and remaining integration boundary

Five focused tests cover three-page automatic traversal, transport/budget stop,
malformed-model JSON continuing as unknown, zero-call completed replay, source/model
mismatch, rehashed missing-page artifacts, interrupted output, and rejection of a
previously reviewed graph. The latter was reproduced as four failing cases before
the pre-call guard was added. The existing extractor, validator and layout module
files remain unchanged.

An isolated python -I process loaded the built batch and extractor modules from
the wheel, rejected development-module imports, and replayed original PDFs plus
seven historical model responses (and one preflight rejection). It reproduced Kia
3 notes/2 tables, Kakao 6 notes/3 tables, Samsung Life 12 notes/3 tables. The batch
selected the same complete table context automatically, returned source-bound
artifacts and replayed its completed cache with no additional client calls.
Coverage remained unknown and decisions null. No new paid model call or source
report/archive modification occurred. This is replay parity, not fresh accuracy.
Evidence: `.local/note-review-integration/automatic-note-batch-replay-v3.json` and
`.local/note-review-integration/automatic-note-batch-wheel-v3/`.
Reproduce: `.venv/bin/python -I .local/note-review-integration/check-automatic-note-batch.py NEW_OUTPUT_DIRECTORY`.

Orca Muse Spark 1.3 Free review: task `task_6f666925b426`, dispatch
`ctx_ab2b9a63e505`, completion `msg_358b85b80097`. Nine local tests/probes were
reviewed; no blocking correctness finding was reported. Its stacking-graph note
was fixed and regression-tested by the coordinator after the review. Its wording
about a live probe referred to a local generated-PDF/client-stub probe, not a paid
model test. Documentation now states exact hash and call-count scope and leaf-only
permissions. Worker released, exact terminal closed and delivery acknowledged.

Live worker wiring must still durably pin automatic mode before the first call,
prevent a missing flag on retry from skipping review, honor cancellation/lease
before each request, and attribute only its own request IDs to usage in the shared
USD10 ledger. This module does not implement those caller responsibilities or
claim that automatic worker composition is complete. Do not introduce another
ledger or infer per-run costs by subtracting global ledger totals.

Final verification: full pytest 1882 passed, 2 existing deprecation warnings,
127.35 s (`.local/note-review-integration/pytest-automatic-note-batch-final.log`).
Ruff passed, full CI mypy passed 167 source files, all package builds passed
(`.local/note-review-integration/build-automatic-note-batch-final.log`).
Documentation/contracts passed 758/758; this is not an application quality score.
