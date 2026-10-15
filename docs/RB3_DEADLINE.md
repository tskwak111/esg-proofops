# RB3 deadline-aware partial publication

RB3 addresses D3's discarded extraction/tagging work at the hosted 1,800-second
subprocess limit. Select `analysis_profile.RB3_POLICY` by its canonical hash in
the operator's `analysis_policy_sha256`; defaults and historical pins are unchanged.

The parent passes its own monotonic hard deadline to the private child. Only a
registered policy containing the exact `rb3_deadline.POLICY` enables admission
checks. At a 1,800-second hard cap, extraction admission stops at 800 seconds and
tagging/inventory admission at 1,200 seconds. Earlier operator hard limits remain
earlier; the policy cannot extend the cap. A stopped stage cannot reopen.

Extraction stops between batches and before new candidate calls. Paid receipts
remain in the normal immutable checkpoint; candidates not sent to a model remain
pending, with unknown spans and `TIME_BUDGET` when stopped inside a batch. Pending
source blocks are not invented claims. Extracted claims already in progress finish
their normal tagging, source checks and rule evaluation. Remaining extracted claims
have a `TIME_BUDGET` hold, empty tags/elements, no grade or decision, and retain their
independently verified source status. Inventory stops before new dispatch and keeps
uninspected scope unresolved. Monetary reservations, three replicas, source/tenant
guards, cancellation fences, and anonymous-FD publication sealing are unchanged.

The pipeline reports `partial_blocked` / `TIME_BUDGET` and adds `rb3_deadline`
metadata. Completed claim projections retain their existing meanings. No schema
migration, new external service, dependency, or model grading authority is added.
Unknown/conflict/unreadable never becomes absent because of this cutoff.

`rb3_claim_source` adapts S4's private policy-DAG evaluation from `bbc91a8` (also
present in final `dda6075`). It retains the FXH reader's nested proof bytes, existing
batch size and raw OCR cache. Each invocation evaluates live code/tool identities;
reader boundaries recheck them. Only the new outer reader policy and artifact hash
change. `rb3_policy_evaluation` caches within one evaluation, not across runs.

For v26 integration, add the RB3 deadline field under a new v26 opt-in hash in
`analysis_profile.policy_for` and `publication_policy_for`, plus the hosted
`prepare_argv` allowlist. Choose the v26 source reader separately; the deadline hooks
do not require replacing its source policy. The optional RB3 reader needs the
additive `PAGE_OCR_PROFILES` registration. Shared edit points are `hosted_r108.drive`,
`hosted_analysis.run_analysis_process`, extraction/tagging admission, inventory
dispatch, deferred-source recognition and public pipeline reason messages.

Rollback stops assigning the RB3 pin to new runs and keeps its reader for saved
artifacts. Existing revisions are never rewritten. No resume or unsealed scratch
recovery path is introduced. The hard kill remains the final fallback if a parser,
an in-flight operation or final verification exceeds its reserved time; a run that
has not extracted a genuine claim cannot manufacture one to avoid a zero count.

Validation uses the real Linux arm64 API/worker/FD path with fresh generated
transports, external network disabled and serialized simulations. Simulator claim
volume and native-derived OCR are not live-model accuracy or latency evidence.
