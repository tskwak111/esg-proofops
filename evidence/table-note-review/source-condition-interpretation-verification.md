# Bounded condition interpretation revisions

The source-review revisions API accepts factual condition proposals with immutable
proposal/assessment separation. The server extracts only complete unit_literal or
scope_literal syntax already defined in the frozen technical contract. Accepted
interpretation requires the original selected canonical note, current confirmed
citation/classification, current accepted ownership for that same fragment and exact
literal refs within it. A client cannot supply a normalized value or accepted result.

All conditions are reevaluated after all ownership assessments on every factual write.
Earlier condition assessments are not authority over new proposals. Conflicting literal
proposals remain conflict; unsupported prose, native proof gaps and uncertain source
quality cannot produce a numeric result. Literal acceptance alone does not establish
per-target coverage or resolve conflicting cell/header dimensions downstream.

The adapter reuses the existing CAS/epoch/atomic revision transaction and immutable
idempotency response. Ownership and condition maps each have a 256-entry bound; request
upserts remain limited to 16 in total. The actual HTTP regression fills both maps,
permits corrections at the limit and rejects overflow without changing the head.
Policy hashes cover ownership, interpretation, numeric literal grammar, reviewed-view
construction and citation verification code. Old input snapshots are unchanged.
New condition writes cannot refer to nonexistent or different-fragment ownership;
this malformed-input path was reproduced before adding its admission check. Existing
records remain reevaluable when a later factual correction changes their relationship.

Orca task task_08c5d3bb095d / ctx_998577be6716 implemented the pure validator and 59
acceptance cases; 241 bounded regressions passed. It settled and was released/acknowledged.
Coordinator integration: 92 focused tests passed with two dependency warnings in 4.93s.
Full suite: **2058 passed, 2 warnings in 150.51s**; log
`.local/note-review-integration/condition-full.log`. Ruff lint/format (291 files), CI
mypy (172 files), architecture checks and all four Python package builds passed.
Document/contract validation passed 785 checks (49 operations), not an accuracy metric.

Read-only review task task_7236b4c36bb6 / ctx_c39528cabe20 found no reproducible
runtime defect after 94 bounded tests, a 37-case malformed raw-entry matrix and exact
runtime/schema comparison. Its report explicitly leaves positive literal HTTP
acceptance/withdrawal and historical parent-retarget execution unverified. The worker
settled and was released/acknowledged; report:
`.local/reviews/source-condition-interpretation-worker.md`.

Actual full local API exercise used committed report checkpoints and synthetic local
reviewer sessions, not independent human/domain-expert validation:

| Report/page | Condition | Revision |
|---|---|---|
| LG Chem/97 | Biomass-note prose remains unsupported; null value | 5 |
| Samsung Electronics/72 | Source transcription/ownership remains unknown; null value | 5 |

Coverage stays unknown, numeric_receipts stays empty, exact retries match, and revision
4 remains unchanged. No new model call or budget-ledger mutation occurred. Private
requests/responses: `.local/note-review-integration/source-condition-write-api-v1/`.
LG revision SHA256: `65068c33d92981d4206266c03c98fda239bcfbc530b785673b50cf6b40d122bd`;
Samsung: `a914d7405323a757876bc310258a2be2fe78512eb6dde93454d0355fda61d4ad`.
Both policy hashes: `88be6fd844394caf1a87899669832da97268be72c40b22a6bb7ffff46e53bba7`.
All 18 installed-wheel checkpoint replays retained their original graph hashes.

Remaining service work: native explicit ownership/derived canonical proof, approved
source view and per-target remainder/sibling coverage, original-backed table role and
claim bindings, actual numeric-check receipt publication and downstream consumers/UX.
Canonical positive conditions have synthetic evidence; the real reports above prove
conservative holds, not positive real-report numeric comparison or corpus accuracy.
Rollback must stop newer source-review writes and retain a compatible historical reader;
an old writer cannot safely reevaluate categories it predates. No production deployment
or automated downgrade path was exercised.
