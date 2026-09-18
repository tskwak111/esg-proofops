# Explicit local Upstage test runtime — 2026-09-12

User explicitly authorized actual model API integration and continued evaluation.
This adds `LOCAL_EXTRACTION_MODE=upstage_probe` only within existing local storage
composition; staging/production remain unavailable. It is local-test authorization,
not a claim that provider processing regions, report rights for public redistribution,
or production readiness are verified. No fake AWS account or ARN is created.

Run creation resolves immutable tenant-scoped registry artifacts. Runtime must be
approved for `provider=upstage`, `purpose=local_test`, `role=extractor`, pinned
`model_id=solar-pro3`, fixed `endpoint=https://api.upstage.ai/v1/chat/completions`,
`budget_limit_usd=10.00`, and have an unexpired `expires_at`. Consent must explicitly
allow that provider/purpose and exact source SHA256 list (no wildcard), with reviewer,
version and approval timestamps. Consent uses the existing document-rights IDs.
Unknown processing geography stays `not_run`; this path cannot authorize deployment.
Existing Bedrock/synthetic preflight behavior is unchanged.

Extraction profile is the actual adapter profile, synthetic=false; run snapshot
freezes `extraction_limits={max_calls: N, max_output_tokens: M}`, N in 1..20, M in
1..1024. Only declared page subsets are enabled initially; paragraph blocks are
sent, unsent text remains unknown. No automatic tagging transport is enabled.
Shared `.local/upstage/budget.sqlite3` remains the cumulative USD 10 authority;
run limits are additional caps. No env-selected alternate ledger or retry loops.
Worker reads UPSTAGE_API_KEY only when explicitly composing real extraction;
caller can load .env.upstage.local without exposing its contents.

Compatibility: no database migration; existing snapshot keys and synthetic modes
remain valid. New optional snapshot/config keys apply only to the explicit new mode.
HTTP request shape is unchanged. Disable the mode to roll back; preserve new
snapshots/receipts and ledger, and do not downgrade them to synthetic. Untagged
review contract is separately recorded in untagged-review-contract.md.

Acceptance: missing/foreign/expired authorization or source hash mismatch prevents
run creation/network calls; immutable real snapshots replay without models;
real upload→parse→extract→claim list/detail reads work locally; honest usage and
unknown states survive partial processing. Grades/source-quality gates unchanged.

Extraction-only rule-pack reference: local Upstage runs may freeze a structurally
validated draft/validated pack as `rulepack_use=extraction_reference_only`, without
activating it or filling approved_by/approved_at. This is not a demo grade grant:
no rules are executed in this stage, and tagging settings are prohibited. Existing
active-pack requirements remain unchanged for every other mode. No migration;
rollback disables new runs and preserves the explicit reference-only snapshots.

## Cost read projection

For upstage_probe only, the existing cost response projects immutable worker attempt
usage records instead of the Bedrock usage ledger. Settled costs use Decimal; any
unsettled or unavailable accounting keeps amount null and cost_status unknown_cost
or partial. Zero calls is unknown_cost. Token totals cover settled receipts only.
No schema/migration or write-back is needed; old runs retain the existing projection.
Rollback is reverting this local-mode read branch; source usage remains immutable.
