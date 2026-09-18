# Original-bound table observation preview

The reviewer/CSRF POST `/v1/runs/{run_id}/source-condition-review/observations`
connects existing explicit-role normalization to the local service. Its 1–16 proposals
reference original canonical cells and a historical source-review revision. Required
roles, same-table/value-row geometry and aligned year headers use the existing shared
normalizer. The response remains `proposal_only` with unknown coverage and preserves
published native-note issues. No observation catalog, review revision, numeric receipt
or grade is persisted. The preview digest pins the request, source/review and current
normalization code; it is not an approval token.

The actual HTTP regression first failed because the adapter method did not exist
(`preview-red.log`). After implementation it checks successful deterministic proposals,
malformed roles/table references, authorization, no job-record/epoch/review mutation,
historical replay after later revisions and rejection of concurrent run mutation.
Logs are under `.local/note-review-integration/`; the final targeted history/race check
passed with two existing dependency deprecations in 5.81s.

Actual LG Chem p97 API exercise generated nine proposals from explicit original cell
roles (rows 1/5/9 and year columns 3/4/5 in native zero-based IDs). Wrong year-column
and metric-row connections returned 422. All three published issues survived; source
review revision 5, its hash, original graph and job-record count were unchanged.
Private request/response/result: `source-observation-preview-v1/` under the same local
evidence directory. Preview SHA256:
`ffaf87298b2b613a7a688255a7adcab94ca4cee6e0805c36ae6f20ae70a2c316`.
This is a local synthetic reviewer session over an actual report, not independent
expert validation. No model invocation or budget ledger mutation occurred.

Ruff lint/format (291 files), CI mypy (172 files), architecture checks and all four
Python package builds passed. Documentation/contracts: 789 checks, 50 API operations;
this is not application accuracy. All 18 installed-wheel checkpoint replays retained
original graph hashes, with zero model calls.

Remaining: native ownership proof, target-level note/remainder coverage, original-backed
claim bindings and actual immutable numeric-check receipts. Ordinary observations GET
still uses automatic header normalization; this additive preview does not silently
replace its catalog. Production deployment, model calls and browser interaction were
not_run in this slice. API rollback removes this read-only route; no DB migration.

Full application suite: **2058 passed, 2 warnings in 146.73s**;
`observation-preview-full.log`. The subsequently added historical/race and foreign-
tenant preview assertions passed separately in the targeted HTTP check above; no
production code changed after the full-suite run began.

Orca implementation task `task_87d89fcaf3da` / `ctx_cf1fd70f2de1` supplied the
additive router/DTO catalogs. Independent review `task_56c23a98ce7b` /
`ctx_026445431e98` found no actionable defect after 15 bounded tests and three
nonintrusive wire-hash checks on the expanded HTTP regression. Both workers settled,
were released and their deliveries acknowledged. The reviewer inspected native issue
preservation and alignment ambiguity; the LG actual API check above exercised native
issue preservation. These checks do not establish positive numeric approval.
