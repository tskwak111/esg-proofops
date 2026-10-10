# Reconciliation local product integration v1

2026-09-21. User authorizes the remaining local product work and real OpenDART
collection with the supplied credential. Preserve G/P/M decisions. No inferred
accounting approvals, paid model calls, cloud deployment, or public release.

## Compatibility and migration before implementation

Keep input/policy/result 1.1 unchanged. C5 remains a separate disabled envelope.
Add local SQLite tables with the `reconciliation_` prefix and an explicit schema
version; never modify or delete existing runs, tags, decisions or exports.
Store immutable draft/import snapshots, review/policy audit events and result
revisions. A head revision advances under a transaction and If-Match. Old readers
can ignore these new tables; rollback disables the new router/UI and preserves
all snapshots. Unknown storage schema versions fail closed.

## Trust

Registration of a prepared case is a server/operator import, never an HTTP
request containing a trusted registry or local filesystem path. Imported document,
fact and coverage bindings remain draft until an authenticated reviewer confirms
the exact snapshot. Imported policy approval records are not trusted: an admin
must explicitly approve the bound policy. Synthetic approvals cannot authorize
real packets. Missing policy or review produces a visible blocked outcome.

Case identity must match the authorized run, its company/document version and an
existing verified claim. Preserve the claim/tag revision that supplied the input.
Source bytes are copied into a controlled immutable store, checked against hashes
and format-aware locators; no external URLs or arbitrary client filesystem reads.
Candidate extraction records original/derived hashes and exact locator lineage;
candidates do not become trusted facts automatically. Human review can confirm
facts and search coverage, never choose a result status or grade directly.

## HTTP surface

Existing cookie session, tenant authorization, CSRF/origin and rate limiting apply.
Mutations require Idempotency-Key and If-Match of the case head revision (quoted
integer). Repeat keys with different input conflict. Cross-tenant reads return
not found. Sources and snapshots use Cache-Control: no-store.

- `GET /v1/runs/{run_id}/claims/{claim_id}/reconciliation`: viewer, `{items: CaseDetail[]}`.
- `GET /v1/reconciliation/cases/{case_id}`: viewer, CaseDetail and ETag.
- `POST /v1/reconciliation/cases/{case_id}/review`: reviewer; body contains
  `reason`, `confirm_source_bindings: true`, `confirm_decision_bindings: true`,
  `confirm_search_coverage: boolean`. Confirms reviewed facts, not policy or verdict.
- `POST /v1/reconciliation/cases/{case_id}/policy-approval`: admin; `approved: boolean`,
  `reason`. Records actual actor/time and policy hash; no default C3 threshold.
- `POST /v1/reconciliation/cases/{case_id}/evaluate`: editor; empty object;
  recomputes with server-owned reviewed snapshots, appends immutable result, returns CaseDetail.
- `GET /v1/reconciliation/cases/{case_id}/revisions/{revision}`: viewer; immutable
  result/projection/provenance snapshot suitable for JSON export.
- `GET /v1/reconciliation/cases/{case_id}/sources/{source_id}/content`: viewer;
  hash-verified original bytes as attachment, never active HTML.

CaseDetail fields shared with UI: `case_id`, `run_id`, `claim_id`, `item`, `revision`,
`synthetic`, `review_state` (pending/reviewed), `policy_approved`, `packet`, `policy`,
`sources`, `latest_result` (null or `{revision, result, projection, created_at}`).
An evaluation can succeed at HTTP level with a blocked result. Inputs and operator
assertions must be distinguishable from verified result sources in the UI.

## Ownership and acceptance

공시 파이프라인과 재무 대사 연계는 동일한 신뢰 경계를 사용한다.

Acceptance: actual HTTP authorization/CSRF/CAS/idempotency, immutable replay,
cross-tenant/source-tamper rejection, unchanged GPM, reviewed vs pending behavior,
policy-unapproved C3, real-source lineage, browser failure and stale-response cases,
type/lint/build and focused regression. Real collection and actual-company semantic
accuracy are separate results. Missing external approval remains visibly pending.

## A-side C2 period input (2026-09-22)

`linkage_exchange_cli.py build-packet --item C2 --c2-period-context FILE` accepts
only `normalized`, `source_id`, `quote`. Dates use `YYYY-MM-DD/YYYY-MM-DD` and
must match one explicit ordered range in the literal. Korean full dates and ISO
dates are supported; ambiguous/multiple ranges remain blocked. No approval flag
is accepted. This adds no HTTP/DB field or migration; older C1/C3/C4 callers are
unchanged. C2 without a supported period stays blocked, replacing the former
incompatible `facility_set` output.

C2 requires a confirmed performance fact with an explicit numeric/unit literal;
categorical certification and year-only literals do not create a trigger. Units
are limited to the existing numeric domain's unit vocabulary. Period evidence
must belong to that fact, match its quote, and retain current-head identity and
source-byte verification. A separate report-wide period cannot silently become
an individual metric's period. Source-verified operator drafts remain distinct
from engine-ready packets and cannot approve policy, promote an unconfirmed tag,
or clear `local_synthetic`.

## Developer B extension (2026-10-09)

`ENABLE_RECONCILIATION=true` explicitly enables the backend store/router;
`VITE_ENABLE_RECONCILIATION=true` enables the frontend route/link. Both default
OFF. Enabling the UI alone does not enable the API. Operator import/from-claim
commands explicitly opt in for their local operation. No feature flag approves
policy, evidence, a verdict, or a G/P/M grade.

Storage version 2 adds tenant-scoped immutable company-to-DART links and audit
events. Version-1 databases migrate transactionally without rewriting existing
case or main-pipeline rows. Unknown versions fail closed. Disable the feature to
roll back exposure; do not delete the version-2 tables or downgrade their marker.

`evaluation.reconciliation_link_company` requires a locally authorized admin
operator, an existing tenant/company and an eight-digit ASCII corp_code. A repeat
of the same link is idempotent; a changed code is a conflict. This local CLI is
not an authentication service: access to the database and operator account is
the deployment boundary, and the actor name is an audited assertion.

`evaluation.reconciliation_filings` lists annual/corrected filings through the
existing bounded client, preserves response hashes and explicitly pins a receipt
into a new file. It never chooses the latest receipt automatically. Network
listing requires `--allow-network` plus `DART_API_KEY`; offline pinning requires
neither. Unsigned pin files provide integrity history, not proof of operator
identity or authenticity. The local operator must authenticate their provenance.

`evaluation.reconciliation_from_claim` consumes a verified current claim/tag head,
the company link, explicit pin and the existing candidate-selection draft. It
uses `build_packet`, copies verified original bytes, and registers a pending case
under tag-revision/mutation-epoch checks. Missing triggers and unsupported source
values are explicit blocks. C5 is disabled. Draft/import policy approval is never
trusted. Main producer gaps (notably currency_amount/revenue_share) are not filled
with invented tags or synonym mappings.

When upload metadata has no publication date, `--sr-published-at YYYY-MM-DD`
accepts an explicit operator proposal and marks its origin in the pending
document binding. It cannot contradict a stored publication date. Omitting it
preserves the visible missing-date block; upload/creation time is never substituted.
`--coverage-proposal FILE` accepts `{search, coverage}` for the rebuilt exact
source IDs. The CLI preserves it as a pending proposal, never generates complete
coverage itself, and only authenticated source/decision/coverage confirmation
makes it available to evaluation. Wrong-tenant, missing-page, truncated and
unconfirmed proposals still block. Every staged PDF supplies its full physical
page inventory; other formats require an explicit consistent unit inventory.

### Review sidecars, without changing input/policy/output 1.1

Document registries can include `coverage_units`: every registered physical page
or allowed note with `unit_id`, `kind` and `locator`. A receipt's
`coverage_manifest` binds `document_id`, `artifact_sha256`, `unit_id`, `locator`,
`readable`, `reviewed`, `source_ids`; each source binding points to its
`coverage_unit_id`. Missing, unreadable or unreviewed required units prevent
complete coverage. Historical document-only receipts remain replayable.
`candidate_limit.truncated=true` prevents complete coverage regardless of the
claimed state; the 2,000-candidate limit is not raised.

`fact_bindings[source_id].period_binding` contains explicit `period_start` and
`period_end`. C4 definition/calculation sources use the same sidecar in
`source_bindings`. With `period_binding_required=true`, missing bindings block;
C4 must match the claim period, while C2 must match the fact's source-bound
normalized period. No report-year-to-fact inference or annualization is added.

Explanation search enumerates registered reviewed sources with the explanation
role inside the receipt scope, in deterministic order. Bytes/locator/quote are
revalidated. The proposal `difference_binding` must exactly bind identity, item,
both facts, comparability, claim and C3/C4 context. Imported `human_reviewed` or
`reviewed_by` has no authority. Only an authenticated review confirming exact
proposals records the source IDs against packet/document/coverage hashes.
`provenance.review_evidence` exposes that confirmation for inspection.

Policy generation is a draft: C3 thresholds remain null and CAPEX allowlists
remain empty. Semantic evaluation only uses explicitly supplied approved gold;
missing gold/outcomes are not_run, synthetic rows are excluded from real-company
accuracy. Expert CSV prose and search_coverage never become approval receipts.

Schema 1.2 and report/export exposure remain **design only**; see
[D-13/D-15 design](handoff/DART_DESIGN_1_2_AND_EXPORT.md). Existing 1.1 schema files
and main export implementation remain unchanged.
