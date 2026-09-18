# Source-condition review contract

Status: persistence, bootstrap/inventory/display and citation/classification revision
HTTP paths, bounded canonical ownership and literal condition validation implemented
locally; approved-view/numeric service integration **not_run**.
Scope: close the path identified in `evidence/table-note-review/service-path-audit.md`
without changing the frozen domain. This document alone does not close that audit.
The first persistence slice uses the existing review store; no model/cloud calls.
It does not yet publish a source-approved graph or invoke numeric checks.
The full local API composition exposes bootstrap POST, inventory GET and original
display GET. Real HTTP checks cover authorization, source pins, no GET initialization,
idempotent bootstrap and publication epoch races. The revisions endpoint records
source confirmation and classification after original-display replay, with atomic
receipt/history persistence, CAS and immutable retries. Ownership proposals now retain
separate server assessments, as do bounded literal conditions. Claim bindings remain
unsupported.

`source_condition_view.render_run_fragment` now loads the committed run's original
PDF, base parser graph and registered note artifacts through `load_run_evidence`.
It renders canonical candidate spans and original-word note fragments, including
notes without canonical IDs. Its receipt pins run/input, graph, fragment, page,
quote, image and reader/renderer/verifier hashes. This is a **display-only** receipt,
not a human confirmation or a source-quality upgrade. The application attaches and
checks source-review revision pins before a factual write consumes it.
The new rendering mode includes default annotations and AcroForm appearances;
XFA, optional-content layers and unsupported geometry fail closed. Historical preview
callers retain their existing default rendering mode. Fragment text preserves parser
ordering, including separately positioned subscripts; the rendered original is needed
for transcription review. Visible annotations absent from native-word inventory must
not be inferred covered by approving all native fragments.

First executable slice: one local `comparison` binding plus a complete unit note,
with explicit row scope already present. Implement source-view confirmation, source
revision GET/POST, CAS/idempotency and an immutable numeric receipt through the actual
API first. Explicit scope-note interpretation, sum/reduction, consumer publication and
cross-report coverage extend the same contract; first-slice success alone does not
close the audit. No routine technical interface needs additional domain approval.

## 1. Existing boundaries to preserve

`ReviewService` edits complete claim-element tags against published `ReviewInputs`;
`LocalSQLiteReviewStore` atomically writes revisions, heads, audit and idempotency
in `job_records`. Its `review_schema` accepts exactly version 1. Reuse those
transaction and authorization patterns, not a fake initial tag or a relaxed P6 writer.
The existing `/v1/reviews/{review_id}/resolve` body remains unchanged and rejects
`note_resolution`, grades and client-created deterministic P6 results.

`native_paragraph_attestation_v1` verifies only native-and-rendered paragraph
text. It does not attest table cells, note ownership, interpretation or completeness.
`replay_native_sources` verifies original bytes and the complete receipt; a matching
artifact hash or a caller's `verification_state=verified` is insufficient.
`ClaimBinding.binding_accepted` is an internal validation result, never an HTTP
permission flag. The pure numeric checker requires the original claim span,
observation lineage, exact dimensions and numeric tokens as well as accepted bindings.

Authority: original v2 §4/§6/§8; docs27; docs28 §§1/4 and its calculation-boundary
clarification; docs31 GAP-003/004/007. Humans edit source facts and relationships.
The model may propose extraction/tags only; Python alone calculates checks/grades.
No source annotation itself changes an element grade, label or legal applicability.

## 2. One immutable source review per run snapshot

Add `source_condition_review_v1`, independent of tag publication. Publish its initial
revision 1 alongside the committed parsing/source-issue snapshot; for an existing run,
use an explicit idempotent publication transaction, not a GET side effect. It contains
all existing unresolved issues and no inferred approvals. An extracted-but-untagged
claim can be bound after extraction; a run with no claims can still review sources.
Do not add these records to the old claim-review queue as if they were claim tags.

Identity pins are server-loaded: tenant_id, run_id, document_version_id,
parse_manifest_id, original PDF source_sha256, base graph_sha256, parse artifact hash,
note artifact hashes (or explicit absence), extraction artifact hash when bindings
exist, and the source-attestation hashes used. Record schema, interpretation-policy,
normalizer and numeric-checker versions/hashes. Existing extraction/tag receipts retain
all replica IDs and model/prompt/rule hashes; a human revision invents none of these.
Changing the source PDF, manifest or extraction snapshot requires a new compatible
review input snapshot/run, never rebasing old evidence silently.

Each revision is a full effective snapshot, derived from its parent plus bounded
upserts; omitted entries are retained. The server computes the revision/hash,
parent hash, actor/time and effective-view hash. Corrections append revisions;
no DELETE endpoint and no rewriting parser graphs, note artifacts or raw candidates.
The following four records are separate even if they refer to the same note:

| Record | Factual input | Server validation/output |
|---|---|---|
| Citation | Candidate identity and exact fragment; `confirmed`, `unknown`, `conflict` or `unreadable`; source-view receipt ID | Validate PDF/graph pins, raw-text offsets, page/bbox and candidate lineage; store human source attestation, not semantic acceptance |
| Ownership | Note fragment, exact target cell/row/table/header source IDs, supporting source refs; `linked`, `unknown` or `conflict` | Validate structural lineage and target coordinates; derive `accepted` only for an explicitly supported relationship |
| Condition | Fragment, owned targets, kind and literal value refs; `tagged`, `unknown`, `conflict` or `unsupported` | Interpret only the finite cases in §3; citation and ownership approval alone do not qualify a condition |
| Coverage | Server inventory of applicable issues, fragments, targets and uncovered intervals | Derive remaining issue/fragment IDs and `complete`, `unknown`, `conflict` or `unreadable` per target; never accept a client completeness flag |

Fragments are `(source_id, candidate parser_run_id/source_native_id, char_start,
char_end, raw_text_sha256)` with Unicode code-point/end-exclusive offsets. Responses
also expose the existing SourceRef page, bbox, quote and hashes. Targets include exact
source ID plus table ID, row/column and spans where present; request coordinates must
match the pinned candidate. Candidate choice is a factual transcription selection;
retain losing candidates and reasons. It cannot approve unresolved structural lineage.

Runtime-discovered notes need a second fragment representation because they often
have no canonical footnote block: `{note_artifact_sha256, packet_sha256,
physical_page, fragment_ids, native_word_indices}`. The server reloads and replays
the pinned artifact against original bytes and requires the exact word union. Client
quotes/coordinates cannot replace this replay. It grants no invented source/table ID.
A derived canonical footnote, if needed by normalization, must retain deterministic
identity and original-word provenance in the reviewed view; the base graph is unchanged.
Page-only proposals stay without ownership until validated target lineage exists.

Classification is a factual tag: `note`, `not_note`, `unknown` or `conflict`.
`not_note` records a false positive such as ordinary narrative or an in-cell data row,
with exact reviewed source/view receipt and reason. It is not an exemption from a true
qualifier. Contradictory evidence remains conflict; the proposal and classification
history remain immutable. There is no blanket `ignore` or outcome-based classification.

For a human citation confirmation the server must first issue a source-view receipt
from authorized original bytes: PDF hash, physical page, rendered image hash, renderer
version, crop coordinates and displayed candidate/fragment hash. The reviewer confirms
what that image says. The receipt proves which source was reviewed, not that the human
is correct. Unsupported rendering, absent geometry or a text mismatch stays unresolved;
new transcription/geometry repair is outside this minimal contract. Paragraph native
attestations may be reused only within their original scope and after validated replay.
A table cell/note requires its own human source confirmation; paragraph approval cannot
be inherited by all children or neighbors.

## 3. Bounded positive condition interpretation

`source_condition_policy_v1` supports exactly:

1. **unit_literal**: a complete fragment accepted by existing `unit_note_literal`.
   Its returned literal supplies the unit of explicitly owned targets. Preserve raw
   unit and the existing `천 ` scale conversion; add no unit conversion vocabulary.
2. **scope_literal**: explicit GHG scope literal `Scope 1`, `Scope 2` or `Scope 3`,
   either the whole trimmed fragment or the value of the complete fragment
   `Scope: <literal>` (colon plus optional whitespace). Store the literal as `scope`.
   Require a source-bound factual scope tag and accepted target relationship; do not
   recognize arbitrary prose by a substring. This only identifies an explicit GHG
   scope, not its applicability to every environmental claim or an organization.

These are bounded source syntaxes, not new rubric thresholds. A review may split a
note into exact unit/scope fragments, but the server retains all non-whitespace text
outside those intervals as unresolved remainder. Punctuation/prose outside the finite
syntax is not silently dropped. Every applicable fragment must qualify before the note
condition gate for a target clears. A literal cannot override a conflicting unit/scope
in a cell/header; retain conflict until factual source selection resolves it explicitly.

Positive example: a located, visibly confirmed note `단위: tCO2e` and a second note
`Scope: Scope 1` are explicitly linked to the relevant numeric row, whose other
source-bound dimensions agree with the claim. The approved view supplies those exact
unit/scope facts, normalization retains their field-to-source associations, and the
service can run `comparison` and obtain `consistent` for matching reported/table values.
This also works with only a unit note if scope is independently sourced in the row.
Neither case asserts that a geographic exclusion has been interpreted.

`해외 사업장 제외`, `데이터 커버리지: 국내`, estimation, exceptions, recalculation
policies and other prose are **unsupported**, even when their words match a claim
or an organizational_boundary cell. Preserve their source, ownership and text; numeric
computation involving them remains `not_computable` with
`footnote_conditions_unresolved`. A human can tag their literal factual content for
review display but cannot switch them to `unit_literal`/`scope_literal` without matching
those syntaxes. There is no `ignore`, `resolved`, `non_material` or blanket approval input.

GHG scope, geographic coverage, organizational boundary and performance calculation
boundary remain distinct. This slice adds no geography→organizational-boundary mapping,
no applicability mapping and no method/assurance inference. Independently explicit
organizational-boundary tags may be preserved through existing binding checks; this
contract does not define a new boundary interpreter.

## 4. Ownership and remaining coverage

Compute relevant notes from retained lineage, not the submitted observation's removable
`footnotes` array. Include the value cell, explicit row/table ancestors, bound dimension
sources and relevant column-header context. Preserve existing conservative unassigned
page-note guards. Two neighboring year columns do not share a note by proximity.

Reviewing note A does not clear note B, a parent table issue, an unassigned note on the
same relevant page, or an unsupported remainder of A. Scope completion is per target:
an unresolved sibling on a provably different target may remain open without blocking
this target only when explicit reviewed lineage proves that separation. Unknown owner
remains conservatively relevant under existing page/table guards. Proposed ownership
must retain rejected/competing target candidates; moving ownership cannot silently
remove an existing contradiction or hide an issue.

Resolved source-condition coverage does not prove complete document search. Parser
page/chunk coverage, unreadable pages and absent-element search coverage remain separate.
Never derive `absent`, `not_applicable`, successful full-run coverage or a new label from
an empty remaining-note list. Return remaining IDs and reasons in every review/check
response, including a successful annotation save whose numeric result is still blocked.

The model proposal list is not a complete inventory. Account for unassigned native
context and unreadable indices as well as proposed notes. Clearing every proposal
alone cannot clear the page hold: preserve reviewed intervals, note/not-note tags,
uncovered intervals and visibility limits. Any uncovered or unreadable relevant
interval keeps coverage unknown/unreadable. A client completeness flag is not evidence.

## 5. Additive API v1 contract

The factual-write slice accepts citations, classifications, bounded ownership and
conditions. claim_bindings must remain an explicit empty array until its validator
is connected; unsupported writes are rejected, never silently stored as accepted.
Classification entries are `{id, fragment, state, source_view_receipt, reason}` with
state note/not_note/unknown/conflict. Citation entries follow the shape below. In
both cases id is the inventory fragment hash and fragment must equal that entry.
Confirmed citations and note/not_note classifications require the exact source-view
payload issued at the base revision. Unknown/conflict/unreadable inputs carry null
receipts. Per-entry classification reasons and the overall reason are 5–1000 characters.
At most 16 upserts per write are supported; larger writes are rejected explicitly.
Original display receipts are replayed before acquiring the write lock; a run epoch
check and source/revision CAS fence the prepared result in the final transaction.
Exact authenticated retries read their immutable response before source re-rendering.
Receipts persist by content hash in the same transaction as the revision/audit/head.
The response is `{review, numeric_receipts: [], coverage_status: "unknown"}` for
this slice. Recording a source fact changes no graph quality, coverage, tag or grade.

Add separate routes; do not alter existing tag-review or observation GET semantics:

- `POST /v1/runs/{run_id}/source-condition-review`: explicit bootstrap for an
  already committed parse, with an empty JSON object. Requires reviewer/session,
  Origin/CSRF and 10 writes/min/user. It is idempotent by the immutable source
  snapshot, without an Idempotency-Key or If-Match: the first call publishes revision
  1, a repeated call returns the existing head, and changed source inputs return 409.
  No source fact is approved. Publication checks the run mutation epoch in its write
  transaction after loading artifacts, so a concurrent run change cannot publish
  stale inputs. Returns the same envelope as GET with 200 and the revision ETag.

- `GET /v1/runs/{run_id}/source-condition-review?revision=N`: current or historical
  immutable snapshot, effective hash and remaining coverage; `200`, no-store,
  `ETag: "N"`. Missing publication is `409 SOURCE_REVIEW_NOT_PUBLISHED`.
  The first read slice returns `{review, fragments, issues, coverage_status}`;
  coverage is explicitly `unknown` until factual coverage validation is implemented.
  Fragment entries are `{id, fragment, text, bbox, physical_page}`. IDs hash the full
  pinned fragment representation; the inventory includes canonical candidates,
  proposed note groups and individual native fragments, including unassigned ones.
  Overlap is retained and cannot count as independent or complete coverage. Inventory
  is bounded at 5000 entries; larger inventories fail with 413 and require pagination,
  never silent truncation. Read-only GET does not initialize review records.
- `GET /v1/runs/{run_id}/source-condition-review/source-view`: query fields
  `revision` and `fragment_id` select a server-inventoried pinned fragment from the
  review response, including native-word notes without canonical source IDs.
  The server resolves the complete fragment representation in §2; clients cannot
  replace its source coordinates or text through query parameters.
  With `format=receipt` (default), return `{review_revision, review_sha256,
  source_snapshot_sha256, fragment_id, display, image_url}`. `display` is the pinned
  runtime display receipt; `format=image` returns the exact original page PNG at
  `image_url`, with the same revision/fragment query. Reuse session authorization
  and the bounded renderer. This read
  publishes no DB records. POST includes the receipt payload with canonical hash ID;
  the server regenerates/verifies it against original bytes before storing it with the
  revision. Unsupported renderer/verifier versions fail closed on historical replay.
- `POST /v1/runs/{run_id}/source-condition-review/revisions`: factual annotation and
  binding upserts. Requires reviewer capability, existing session/Origin/CSRF checks,
  bounded JSON, existing review limits (10 writes/min/user), `If-Match: "N"`, and
  `Idempotency-Key` length 16–128. GET uses reviewer capability and 120/min/user.
- `GET /v1/runs/{run_id}/numeric-checks/{receipt_id}`: immutable receipt under the
  same tenant authorization, no-store. No free-standing client result submission.

The POST strict top-level shape is `{schema_version: 1, base_source_revision: N,
source_snapshot_sha256, classifications: [], citations: [], ownership: [], conditions: [],
claim_bindings: [], reason}`. Reason uses the existing 5–1000 character review bound.
Strict entry shapes:

- citation: `{id, fragment, state, source_view_receipt}`; receipt required for confirmed,
  otherwise null; fragment uses the exact tuple field names in §2.
- ownership: `{id, fragment_id, targets, state, evidence_refs}`; each target contains
  `source_id, table_id, row, column, row_span, column_span`, with structurally
  inapplicable fields null; existing SourceRefs support the marker/heading linkage.
- condition: `{id, fragment_id, ownership_id, kind, state, value_refs}`; kind is
  `unit_literal`, `scope_literal` or `unsupported_prose`; unresolved/unsupported
  interpretations have no normalized value and empty value_refs.
- claim binding: `{id, claim_id, kind, observation_ids, reported_value_ref,
  dimension_refs, quantity_kind, aggregation}`; dimension_refs maps only the fields
  below to source-ref arrays, empty for null dimensions; aggregation is null except
  for an existing source-bound sum relation proposal.

All arrays may be empty individually; at least one factual upsert is required. Each
entry has a stable ID and all fields defined in §2; the client uses IDs/refs from GET.
Unknown keys/enums and duplicate or contradictory upserts return 422. Status fields
listed as server outputs are forbidden in requests, including `binding_accepted`,
`coverage.complete`, check status/value, grade, label and rule-gap resolution.
A condition's value refs must reproduce its literal and lie inside its cited fragment.

`claim_bindings` proposes `kind`, claim ID, ordered observation IDs, reported-value
SourceRef, field-to-source refs for metric/unit/scope/subject/period/basis/boundary/
denominator and quantity_kind. Optional baseline-period refs are required for reduction.
The server loads the registered claim and observations, derives normalized field values
and verifies the full reported number lies inside that exact claim span. Claims and
values/years need local-claim or directly linked same-table evidence; unrelated global
numbers are refused. Scope/method/assurance global admission still follows approved
source-scope contracts. Acceptance is not inferred from equal numbers or same page.
For sums, require the existing source-bound `disjoint_complete_components` relation
and its complete ordered member list; do not invent sum ownership from adjacent rows.

A valid write returns `200` with `{review, numeric_receipts}` and the new ETag. Review
contains new revision/hash, immutable input pins and remaining coverage. Receipts include
one current check for each retained affected accepted binding, or a blocked result for
an unresolved candidate binding; no bindings means `numeric_receipts: []`. A saved
unsupported condition is successful factual recording, not successful computation.
Invalid/mismatched refs return `422 SOURCE_OR_BINDING_REJECTED`; unavailable or altered
pinned artifacts return `409 SOURCE_REVIEW_INPUT_MISMATCH`. Foreign tenant/run/source
access returns 404 without revealing source existence; viewer write is 403. Missing or
malformed If-Match is 400 (existing review convention), stale revision/body base is 412,
request replay conflict is 409. No receipt or partial revision persists on rejected writes.

## 6. Transaction, schema and replay

Current storage slice: `publish_source_conditions`, `source_conditions`, and
`resolve_source_conditions` in `LocalSQLiteReviewStore` implement the four
`source_condition_*` kinds below. Publication records a system actor/time and an
audit event. Reads verify immutable backing records, input/revision hashes and the
current head against the latest revision; explicit historical reads remain available.
The transaction callback is an internal application boundary, not a user-supplied
function or a source validator. The application now replays displays before writes;
source-view receipts are deduplicated and persisted atomically with source annotations.
Numeric receipt writing and downstream approved condition views remain unimplemented; ownership
assessment uses a transient canonical citation view and does not publish it downstream.
Synthetic storage inputs alone prove no source approval.

Use existing SQLite `job_records` and audit transaction; no new database backend,
network dependency or generic workflow framework. Add a separate
`source_condition_schema(version INTEGER PRIMARY KEY)` containing only 1; unknown
versions fail closed. Do **not** bump `review_schema` to 2: its current reader rejects it.
Add kinds `source_condition_inputs`, `source_condition_revision`,
`source_condition_head`, `source_condition_idempotency`, `numeric_check_receipt` and
`source_view_receipt`. The head alone is mutable. Add separate INSERT-replacement,
UPDATE and DELETE guards for all new immutable kinds; do not weaken existing triggers.
Initialization is idempotent and one migration transaction; old payloads are not rewritten.
Record IDs include review revision or content identity; lookup always includes tenant/run.

Load/replay immutable inputs outside the write lock if necessary, as existing reviews do.
Inside one write transaction: authorize current ownership, check idempotency, compare
head N and input pins, verify artifact identity, validate upserts and compute approved
view/bindings/checks, append revision/receipts/audit/idempotency response, advance head
and run mutation_epoch. Any error rolls back all writes. Recheck extraction pins when
binding claims. Concurrent requests with the same base and different keys yield exactly
one 200 and one 412, never two successor revisions.

Idempotency identity is `(tenant, actor, operation, key)`; request hash includes run,
If-Match and canonical full body. For an authenticated identical retry, replay the stored
status/body/ETag before stale-head checks, even if later revisions exist. Different body,
run or expected revision with that key returns 409. Failed transactions create no key.

Receipts pin source-review revision/hash, effective graph hash, extraction/observation
snapshot hashes, accepted binding payload/hash, source attestation and policy/checker
hashes, exact original refs, check result/reasons and execution profile. Human actor/time
are audit metadata, excluded from semantic computation hashes. A numeric receipt is not
a decision revision. New tag packets must pin the approved source revision and receipt;
rule evaluation creates a new immutable tag/decision revision under existing publication
CAS. Old packets, replica receipts, decisions and exports retain their original pins.

## 7. Shared consumer integration and rollback

One trusted loader produces the approved immutable view for normalization/numeric,
retrieval and tagging. No endpoint-only `issue.state = resolved` branch. Preserve the
base graph and expose exactly which issue/fragment each annotation qualifies. Numeric
checks consume typed approved conditions with their provenance; merely removing an
issue cannot bypass `_unresolved_footnotes`. The application actually calls
`check_numeric_consistency`; observation GET alone is not this integration.

A run without a source review follows its current conservative path. New derived
artifacts use explicit new versions/pins; old artifacts are replayed under their old
versions. Unknown versions or a missing required receipt fail closed. No consumer may
mix latest source conditions with an older packet while retaining the old packet hash.
P6 is populated only through the stored deterministic receipt, and GAP-003 still blocks
any undefined grade effect. No LLM call is needed for source review or numeric checking.

Rollback: stop the new writer/consumer assignment and hide new routes; retain schema,
triggers, audit and immutable artifacts. Old readers can ignore new kinds for old runs.
New source-dependent runs/artifacts must be fenced from old consumers, not downgraded
by dropping their pins. If that fence cannot be enforced, keep those runs read-only on
the compatible reader. Restore the old deployment for unaffected runs; never drop the
new tables/kinds or rewind heads to old revisions. A factual reversal uses a new revision.

## 8. Required real API acceptance (not yet executed)

Use the existing local app composition, session/CSRF machinery and SQLite stores via
HTTP TestClient; a local synthetic input fixture is explicit, not customer verification.
Exercise real source-review routes, trusted loaders, normalizer and pure checker.
Do not mock the service/checker to return expected results or pre-mark graph issues
resolved. A generated local PDF/render receipt may make source-confirmation tests
repeatable; native paragraph attestations must retain their structure exclusion tests.

| Case | HTTP sequence and required assertion |
|---|---|
| Untagged positive unit/scope | Publish committed source/extraction with no tag; GET revision 1; POST confirmed exact cell/note citations, supported ownership, unit/scope tags and comparison binding; 200 revision 2 and receipt `consistent`; receipt GET returns identical pins/result; claim remains untagged until separate publication |
| Unit-only positive | Same with explicit independently sourced row scope and `단위: tCO2e`; actual checker returns consistent after approval and not_computable before it |
| Scope precision | Valid explicit Scope 1 note qualifies; malformed/suffixed prose remains unsupported; Scope 2 observation vs Scope 1 binding cannot compute as consistent |
| Wrong association | Swap row, year column, claim number span, source version or table ID in otherwise valid POST; 422/409 as above and unchanged head/audit/receipt count; equal numbers do not rescue wrong lineage |
| Sibling/remainder | Approve A with B open; 200 save but receipt not_computable and B retained; append unsupported prose to A and confirm only unit prefix: non-whitespace remainder still blocks |
| Proven unrelated sibling | B has explicit reviewed different-column ownership with no shared parent ambiguity; A can compute, B remains open; removing proof restores conservative blocking |
| Geography | `해외 사업장 제외` and coverage 국내/해외/글로벌 stay footnote_conditions_unresolved even with equal organizational-boundary tokens; no boundary fact generated |
| Source gate | Reuse paragraph receipt for a cell/note, tamper crop/PDF/quote/hash, or confirm unreadable geometry; rejection or unresolved state, never verified inheritance |
| CAS | Two POSTs at ETag 1 with different keys: one 200, one 412; body base differs from ETag also 412; absent/malformed header 400 |
| Retry | Exact retry returns first response/ETag and one audit event even after revision 3; same key with changed payload/run/base yields 409 |
| Auth | Viewer POST/invalid CSRF 403; foreign run/source 404; no mutation or cross-tenant receipt lookup |
| Client outcomes forbidden | POST check status, binding_accepted, grade, label, complete or blanket resolved: 422; old review route still rejects note_resolution and fabricated P6 |
| Atomicity | Inject local storage failure between receipt/audit/head writes; transaction leaves all counts/head unchanged, same key can retry successfully |
| Shared consumers/history | New numeric/retrieval/tagging artifacts pin identical source revision/effective hash; after factual correction old GET revision/receipt/export bytes are unchanged, stale packet reuse is rejected |
| Schema/rollback | Initialize twice, immutable UPDATE/DELETE/INSERT OR REPLACE fail; old v1 review tests still pass; unsupported source schema rejected and old consumer cannot silently process new pinned artifacts |
| Domain gate | Deterministic consistent receipt does not itself yield E3 or clear GAP-003; evaluate real frozen rulepack and assert null grade/label where its gap applies |

Implement these in `tests/acceptance/test_source_condition_reviews.py`, retaining
existing numeric/review/tenant regressions. They specify executable HTTP acceptance,
not claims of passed checks. Lint/type/unit/integration/contract/build/E2E/security
commands/results belong to the implementation evidence; model/AWS tests remain not_run.

## 9. Minimal implementation files and unresolved decisions

Expected production touchpoints (root verifies runtime paths independently):
`application/reviews.py` for the separate source-review service/strict validation,
`adapters/local/review_store.py` for new kinds/transaction/migration,
`apps/api/src/proofops_api/routers/reviews.py` for separate routes/DTOs,
`apps/api/src/proofops_api/local_runtime.py` and `composition.py` for wiring,
`adapters/local/run_artifacts.py` for pinned shared loading,
`application/ingest/normalize.py` and `domain/numeric.py` for approved typed conditions,
`application/tagging/service.py` and retrieval packet construction for revision pins
and deterministic receipt consumption, and `adapters/local/source_verification.py`
for source-view/human receipt validation. Existing SourceRef/citation/binding functions
should be reused. Add only a small pure condition DTO module if importing application
records would violate Domain dependencies. Update OpenAPI and
`contracts/jsonschema/api_models.schema.json` additively alongside routes; no change
to frozen rubric files. One new acceptance file plus necessary existing regressions.

Not derivable from frozen sources, therefore intentionally unresolved:

- How arbitrary geographic exclusions/coverage, estimation or exception prose changes
  comparability or establishes a calculation/organizational boundary. This needs a
  source-specific approved interpretation with boundary examples, not word equality.
- Non-GHG scope applicability and any newly proposed condition vocabulary outside the
  finite literal path. Preserve unknown applicability until approved mapping exists.
- P6 consistent/inconsistent/not_comparable/not_computable effects on all final-grade
  combinations: GAP-003 approval must specify vectors and rulepack hashes.
- Broader source-scope permissions for numbers/years: GAP-004 remains unchanged.

No approval question is needed to implement the bounded factual/technical path above.
Source confirmation/ownership can be reviewed before these semantic gaps are settled;
unsupported conditions remain visible and blocked. Completing the positive API path
and the cross-report unsupported/sibling behavior, with recorded execution evidence,
is required before declaring the original service-path audit closed.


## Ownership write implementation contract (2026-09-14)

The additive ownership slice accepts the existing §5 ownership shape, at most 16
upserts per request across all categories and 16 targets/32 evidence refs per entry.
Condition and claim-binding arrays remain empty. Each stored ownership value is
`{proposal: <unchanged factual entry>, assessment: {id, state, reasons, policy_sha256}}`; accepted
is server-derived, never client input. All effective ownership entries are reevaluated
when a citation or classification changes, including entries omitted from a write.
Old revisions and their assessments remain immutable. Full-page coverage remains
unknown and no numeric receipt/grade is emitted by this slice.

The first supported ownership proof is an existing explicit canonical `footnote_of`
relationship with exact selected target geometry/table ancestry, confirmed source
citations and note classification, and original-bound evidence refs. Mere proximity,
a model target proposal or the native marker candidate filter cannot prove ownership.
Native fragments stay unknown until a separately supported explicit proof is available;
they remain in the inventory and continue to block relevant coverage.

A transient reviewed canonical view may mark only an already selected, wholly cited
unverified candidate as source-verified after its server-replayed display confirmation.
It cannot choose a losing candidate, repair conflicted/unreadable geometry, promote a
native fragment into a canonical block or clear any issue. This view is rebuilt from
each effective citation state; withdrawing confirmation therefore withdraws dependent
ownership acceptance. Its use is restricted to this validator until downstream approved
view consumers are integrated. Base graphs and parser artifacts are unchanged.

Storage uses the existing immutable source revision schema; no new table or migration.
Old clients with empty ownership arrays remain valid. Rollback retains new revisions for historical GET using the compatible reader; stop
source-review writes before reverting writer code. A prior writer does not reevaluate
newer assessment categories and must not process those runs. No old record is rewritten. This does not close the service-path audit or supply numeric comparison.

Ownership snapshots are capped at 256 effective proposals; a new ID above this bound
returns 413 SOURCE_REVIEW_OWNERSHIP_LIMIT before the additional ownership graph replay/reassessment. Existing
IDs can be updated at the limit; earlier immutable revisions are retained. This bounds
whole-snapshot CPU/storage until a paginated workflow is implemented. policy_sha256 is
the canonical hash of the ownership-validator, reviewed-view adapter and citation
verifier file SHA256 values. It is server-computed for each new assessment, not added
to source inputs; historical assessments without this field remain readable and are
not retroactively assigned the current implementation. Exact retries keep old pins.


## Condition write implementation contract (2026-09-14)

The revisions operation additionally accepts the §5 condition proposal shape. It keeps
`{proposal, assessment}` separately; assessment includes id, accepted/unknown/conflict/
unsupported state, a server-derived literal value or null, reasons and policy_sha256.
Only the two complete §3 literal syntaxes are interpreted. A tagged value requires a
confirmed note citation/classification, an accepted ownership assessment for that exact
fragment and selected original refs wholly inside the fragment reproducing the literal.
Unknown/conflict/unsupported proposals contain no value refs. There is no client value,
coverage-complete, numeric result or grade field.

Reevaluate every effective condition after ownership reevaluation on every factual write,
so citation/classification/ownership withdrawal cannot leave an accepted interpretation.
Retain all unsupported prose and siblings; condition acceptance alone does not clear
coverage or publish an approved graph. Native fragments remain unresolved until the
native source/ownership proof is implemented. A canonical partial fragment cannot
silently suppress its remaining source text.

Each category has at most 256 effective proposals; all request arrays together still
have at most 16 upserts. New condition IDs over the cap return 413; updates at the cap
remain valid. Reuse immutable source revision schema and CAS/idempotency transaction;
no DB migration. Old clients with empty conditions remain compatible and historical
records are not rewritten. New policy hashes cover ownership, interpretation, numeric
literal grammar, source-view construction and citation verification implementations.
Rollback stops source-review writes and retains the compatible reader and immutable
GET/retry records; do not run an older writer against condition-bearing revisions.
Claim bindings and numeric receipt publication remain unimplemented in this slice.

New condition upserts must reference an existing merged ownership proposal for the same
fragment; foreign/missing ownership IDs are rejected even for unresolved condition input.
Existing condition records are retained if a later ownership correction changes the
relationship; their assessment becomes unresolved rather than blocking that correction.

## Read-only table observation preview (2026-09-14)

Reviewer/CSRF POST `source-condition-review/observations` accepts a pinned positive
review revision, original table UUID and 1–16 explicit cell-role bindings. Existing
normalization validates required metric/year/value roles, table membership and row/
column geometry. This computes proposals only: it neither persists a revision nor
approves evidence, coverage, numeric consistency or grades. Original published issues,
including native note warnings, survive normalization. Historical revisions remain
readable; concurrent run mutation rejects the preview. Output pins the source snapshot,
review hash, normalization implementation and exact request with a deterministic hash.
That hash is reproducibility metadata, not an approval credential. Future claim binding
must replay these inputs against the pinned original rather than trust preview output.
No database migration or change to ordinary observation GET. Rollback removes only this
preview route, retaining all source revisions and existing observation catalogs.

### Per-observation source holds

Observation previews additionally expose `source_holds`: one entry per observation,
with `observation_id`, sorted `issue_ids`, `note_source_ids` and `reasons`. These are
server-computed diagnostics from the same original-lineage checks used by numeric
comparison. Include inherited table issues, unassigned notes on relevant pages and
notes owned by bound dimensions or relevant year headers. Retain every applicable
hold even when another source is already unverified. An empty list of holds is not
coverage approval or permission to calculate: the outer preview remains proposal-only
and coverage unknown. No historical graph or review is altered; this additive response
field can be removed on rollback without storage migration.

## Native note target inventory v3

Version 3 includes table cells reached through retained `table_parent` row ancestors,
in addition to direct table children. Each target still identifies its original source
and unique root table; conflicting/unresolved row or table ancestry remains in
`unresolved_source_ids`. This repairs missing candidates, not source geometry or semantic
ownership. Do not broaden marker proximity/clip rules to compensate for broken tables.
New packets use contract version 3. Version 2 packets retain their direct-child inventory
for byte-identical replay; unsupported versions fail closed. Recognized historical
validator/layout hashes may only replay the version-2 contract. No existing artifact,
checkpoint, source review or model receipt is rewritten. Rollback stops v3 creation and
retains a v3-capable reader; an old reader cannot consume new v3 packets. No DB migration.

## Original glyph geometry in native source displays

Native source displays may add `glyph_geometry`, a source-bound diagnostic comparing
pdfplumber native word characters with PDFium glyphs. Match identical Unicode and the
original text-matrix origin within 0.001pt (reader floating-point serialization tolerance),
never word text or proximity alone. Every mapped character needs one unique original
PDFium character, valid tight glyph bounds and unchanged native word identity. Preserve
font boxes alongside glyph boxes; ambiguous, missing or degenerate mappings stay
unresolved. No canonical/source geometry is overwritten. The display highlight remains
its original fragment box; an ink box is not a new source, repaired cell or ownership tag.

The diagnostic pins original PDF hash, physical page, native words, PDFium character
indices, reader and matcher hashes. It is part of the existing source-display receipt
hash and independently recomputed on replay. Absence/unavailability is null; a partial
mapping carries unresolved word IDs and no overall ink box. Source display, glyph
agreement, transcription confirmation, note ownership and condition coverage remain
separate. Existing source-review revisions and stored receipts are immutable. Pending
receipts from an unsupported verifier build need a fresh display, as before; exact saved
write retries retain their old result. Additive display metadata requires no DB migration
or new API route; rollback removes the diagnostic and retains historical records.

### Explicit table text line tolerance (2026-09-14)

ParserProfile accepts optional `table_text_y_tolerance`, a finite nonnegative number
in PDF points (booleans rejected), forwarded only to pdfplumber `Table.extract`.
Table discovery, cell boxes, provenance, and quality assessment are unchanged.
Absent/None retains the installed parser default and is omitted from both invocation
and configuration snapshots, preserving historical manifests, checkpoints and hashes.
An explicit value participates in both hashes and requires a new parse invocation;
old immutable graphs are never rewritten. Canonical configuration files omit this key
instead of spelling an explicit null, following existing snapshot equality checks.

This is an operator-selected extraction setting, not an automatic superscript repair
or evidence approval. Larger tolerances can merge distinct lines; validate the chosen
profile against the original document. The observed POSCO p139 total label is read as
`합계2)` at 4 points instead of the default reversed lines. This does not resolve the
incomplete table structure, clipped font bounds, native note ownership or coverage.
No API/DB schema or migration changes. Rollback uses the prior default profile for
new runs and preserves custom-profile artifacts; old readers reject unknown custom
options rather than silently reinterpret them.

### Canonical glyph containment fallback (2026-09-14)

A canonical source view that fails font-box text/containment checks may use original
PDFium glyph bounds. All existing source, candidate, page, crop, rotation and optional
content checks still apply. The bounded mapper examines every native word (maximum
1000 words/20000 characters). Any unresolved native word whose font box intersects
the candidate prevents fallback. Matched words must have fully contained glyph boxes;
an independent scan must account for every intersecting non-whitespace PDFium glyph.
Invalid/unlocated non-whitespace glyph bounds anywhere on the page remain unsupported.
Unresolved words outside the candidate are not promoted or considered page coverage.

Selected native-word glyph indices must be unique and increasing in the original
word order. Text is reconstructed from the original PDFium Unicode sequence; only
whitespace may intervene between selected glyphs. Exact existing normalized full
candidate text equality is required. No invented word-separator spaces, superscript
reordering, fuzzy text matching or numeric whitespace deletion is permitted.

Fallback receipts include `glyph_selection_word_indices` and compact
`canonical_glyph_selection_v1` geometry: original SHA/page, selected original word/glyph
mappings, full-page mapping hash and selection hash. Full replay recomputes the whole
mapping and source text; the hash is not client authority. Compact geometry avoids
repeating every page word in each citation request. Native-note diagnostic shape is
unchanged. Receipt scope remains source_display_only: glyphs do not prove rendered
visibility, semantic note ownership, source completeness or condition acceptance.

Original candidate boxes/text/quality and immutable graphs remain unchanged. Source
transcription can be confirmed only by the existing explicit citation review workflow.
Historical stored revisions and exact retries remain immutable; new writes require a
fresh supported-verifier receipt. No API route/DB schema migration. Rollback removes
fallback for new displays, preserves saved revisions and rejects unsupported receipts.

### Source-derived native marker ownership (implementation contract)

The existing ownership request shape remains unchanged. Clients cannot supply an
acceptance flag or native proof. For a linked native-note proposal the local adapter
replays the committed original note artifact and source views to derive an internal
`native_note_marker_v1` proof. A proof pins tenant, document version, parse manifest,
source and immutable parser graph hashes, exact native fragment identity/word indices, one
marked leaf cell and the original base/raised-marker word identities.

A unique same-number raised marker in a source-confirmed leaf, compatible original
note/table column geometry, absence of competing marked candidates, confirmed note
transcription/classification and verified original leaf/table/ancestor references
are all required. Geometry or a repeated page number alone never suffices. Acceptance
binds only that marked leaf, not the whole row/table and not completeness of the note
or page. Arbitrary note prose and native condition interpretation remain unsupported;
no numeric receipt, grade or coverage completion follows from ownership acceptance.

The pure ownership validator accepts the replayed proof only as an internal keyword
argument and validates its identity pins. The adapter recomputes the proof whenever
assessing effective ownership; the revision assessment retains its digest and policy
hash. Existing immutable revisions/exact retries remain unchanged. No route or DB
schema migration; rollback restores unknown native ownership on new assessments and
preserves historical records. Actual release verification must establish implementation
of this contract before claiming support.
