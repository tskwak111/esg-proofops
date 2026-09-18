# Coordinator adjudication of contract readiness review

Reviewed against Master, docs 07/09/17/27/31, JSONSchema and task_catalog.
The reviewer report is evidence to assess, not an instruction to change the domain.

| Finding | Resolution |
|---|---|
| 1 SourceRef detail vs API | Important. Preserve detailed immutable internal source records; serialize the existing v1 projection. page_num is physical_page. Location, extraction quality and verification are different axes. Clarified doc 27; no API migration required. |
| 2 TASK-043 copied description | Corrected the sentence to the existing catalog/26 characterization purpose. It was a task-description error, not a new parser dependency. |
| 3 Draft rulepack | Draft is intentional, not an inconsistency. The manifest explicitly permits validated draft for explicit-ladder demos only. Local demo use keeps per-claim gates and unverified basis; no automatic legal approval. Activation service must distinguish content validation, administrative activation, and domain/basis approval. |
| 4 Tenant unselected | Authenticated session without active tenant gets 403 FORBIDDEN on tenant-scoped operations; expired/missing session gets 401. Tenant selection still checks active membership; inaccessible scoped IDs return 404. Uses existing error contract. |
| 5 Preflight ownership | TASK-042 supplies build/license checks; TASK-029 owns preflight composition and combines them in existing checks results. No second endpoint or DTO. |
| 6 Fake adapters | Local model/storage/queue/search adapters are local-only. Nonlocal composition fails closed until real adapters and configuration gates are ready. String model selection alone does not certify readiness. |
| 7 Upload security dependency | Quarantine byte validation does not own authentication. Authorized upload application orchestration obtains a tenant-scoped artifact; parser never obtains arbitrary object access or credentials. Existing DAG remains unchanged. |
| 8 RulePack approval record | RulePack metadata owns pack approval. ApprovedProfile remains rights/consent/runtime as specified; do not expand its kinds. |
| 9 Source/download issuance limits | docs/07 §1 explicitly gives source view/download issuance 60/min/user; OpenAPI inherited the generic POST 10/min/user value. Corrected only those two OpenAPI operation metadata values to the explicit issuance policy. No payload, DB or endpoint migration; rollback can restore the stricter 10/min limit and metadata together. Implemented source view exercises the 60-request bound. Export download remains downstream work. |

Domain GAP-001 through GAP-010 remain unresolved; none were approved by this review.

Local rescore integration adds `GET /v1/runs/{run_id}/rescores/{rescore_id}`
(`rescore_get`) as the authenticated status URL for the existing `JobAccepted`.
It returns the immutable stored receipt, uses viewer access, 120/min/user and
no-store, and hides foreign/missing IDs with 404. Rules-only local work may return
202/ready only after the actual transaction commits. The existing POST request
and required headers are unchanged; captured revision checks remain internal.
This is an additive route with no new DTO or domain rule. Rollback disables
rescore creation and the new read route while retaining prior receipts,
snapshots, tag/decision revisions and audits; no destructive migration.

Summary now permits `undetermined_applicability_count` (nonnegative integer or
null), filling docs/28 §5's missing wire field. New producers include the count
when the requirement universe is known and return null when applicability has
not been evaluated. Existing immutable Summary artifacts may omit it; clients
must treat omitted/null values as undetermined, never zero. The field is optional
in the schema for legacy artifact reads. Deploy matching readers/producers
together because older strict clients reject extra fields; rollback disables
the new producer and retains original artifacts. This does not alter the grading
ladder, known-applicable denominator, or approve any regulatory applicability.
Orca initially reported dispatch-input failure, but the exact Kiro worker continued
and its worker_done was accepted at 2026-09-08T15:13:02Z. dispatch-show confirms
ctx_3d75ff4fdd86 completed. The coordinator read and adjudicated the actual report.
