# Remaining service integration gap

Orca audit at `5f7d93f`: task `task_c41f28f2a06a`, dispatch
`ctx_396e295bb9eb`, completion `msg_dd67dfa21f95`; worker released. This is
an observed implementation gap, not a request to change the frozen ESG rubric.
Full private audit: `.local/note-review-integration/note-condition-service-audit.md`.

Runtime note artifacts currently create open source issues. Numeric checks,
retrieval and tagging honor them. Existing human claim-tag review uses If-Match
and immutable revisions, but cannot adjudicate source quality, note ownership or
note conditions. Extracted-but-untagged claims cannot bootstrap that review.
`check_numeric_consistency` currently has no production caller in `packages` or
`apps`; the observation API does not run it. Removing an issue alone would not
provide a supported condition interpretation.

The auditor ran 247 focused acceptance/integration checks successfully. A separate
synthetic probe, using `tests.acceptance.test_numeric.case/row`, established:

| Original note | No issue | Open note issue | Issue marked resolved in the probe |
|---|---|---|---|
| `단위: tCO2e` | consistent | not_computable | consistent |
| `해외 사업장 제외` | not_computable | not_computable | not_computable |

The probe's in-memory issue replacement is not a supported service approval.
Adding `note_resolution` to the current review body is rejected with 422.
Source tests and existing reviews correctly prevent a caller from typing in P6
`present/consistent` without a dedicated deterministic result.

## Required next implementation

1. Define a source-bound annotation revision available before claim-tag publication:
   exact note fragments, explicitly accepted source/target lineage, condition tags
   and unresolved remainder. Source quality, ownership, interpretation and coverage
   stay distinct. Preserve tenant/document/manifest/source/artifact hashes.
2. Define its authorized reviewer command, CAS/If-Match, idempotency, immutable head
   and historical replay, compatibility and rollback before adding a writer. Reuse
   the established transactional review/audit patterns. Never mutate old parser
   checkpoints or accept a plain `resolved` string as condition interpretation.
3. Make numeric/retrieval/tagging readers consume the same approved revision, then
   invoke the pure checker from the application with verified observations and
   accepted claim bindings. Store an immutable check receipt. Human/model inputs
   remain tags and source bindings, never grades or numeric check outcomes.
4. Prove a qualified numeric example through the real API, including stale revision,
   wrong row/year/tenant, unresolved sibling notes and unchanged historical results.
   Keep undefined P6 grade effects blocked under GAP-003; no invented rubric mapping.

Further extraction scores alone cannot close this gap. The overall goal remains
active until this path and the required cross-report behavior are verified.
