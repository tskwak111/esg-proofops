# Autonomous completion plan — active, 2026-09-19

Objective: implement and verify all work possible under existing user authorization,
not merely finish another diagnostic. External product calls share the original
USD20 cumulative ledger. Domain gaps and independent human gold remain unresolved
where unavailable. Antigravity/OpenCode first; Codex Terra/Luna only after those
providers are exhausted/blocked. Other developer ownership remains respected.

User stop condition: check Codex subscription quota through `orca account list
--json` (only report `rateLimits.codex`, never credentials/account metadata).
When remaining usage reaches 10% or less, start no new work; finish bounded
verification, save changes and handoff state, release workers, then stop. Do not
mark the full objective complete or spend reset credits automatically. A cached
quota timestamp is not a fresh measurement; session limits may be unavailable.
For a stale Orca cache, use local `codex app-server --stdio`: initialize a client,
send `initialized`, then read `account/rateLimits/read` with
`excludeResetCreditDetails=true` and `supportsLunaReserve=false`. Terminate that
read-only server after the reply; never start a model thread or spend reset
credits. Inspect the ordinary `codex` limit, not a separate reserve-model bucket.
Direct read on 2026-09-18 16:40 UTC: 68% used / 32% remaining (weekly), ordinary
usage allowed. This is a dated observation, not an indefinitely current value.

## Remaining completion evidence

- [ ] Real local execution: independent immutable extractor/preliminary/element
  settings and approvals; durable preliminary response, retrieval and relationship
  suppliers; correct token reservation and actual usage; worker/API integration.
  Verify actual PDF→model→review with explicit failures, cancellation/restart and
  no duplicate billing. Never disguise real calls as synthetic.
- [ ] Evidence quality: broaden body/data/appendix retrieval in the worker; verify
  native paragraphs/tables/notes; preserve year/unit/entity/boundary mismatches and
  unresolved conditions. Real multi-layout development comparisons required.
- [ ] Model quality: source-bound claims, classification, element/relation tags;
  repeated multi-report evaluation with failure records. Independent gold metrics
  remain unmeasured until independently adjudicated data exist.
- [ ] Product integration: actual source viewer, candidate vs accepted evidence,
  tag editing/CAS, deterministic rescore, immutable reports and source links.
  Verify with a real browser flow, not only mocked APIs.
- [ ] Full integration: consume Developer B output when available; validate all
  contracts and error cases; retain unresolved C1–C4 where input is unavailable.
- [ ] Verification and delivery: relevant security/lint/type/test/build/E2E checks,
  bounded cost/latency/coverage evidence, executable commands and clean reviewable
  commits. Actual cloud/deployment authorization and independent domain decisions
  are external gates, not permissions inferred from software tests.

## Current work: authorized preliminary transport

Reuse existing UpstageTaggingTransport request authorization, local lock,
create-only receipts, durable stop/incomplete detection, shared UpstageProbe USD
ledger and RawTagResponse. Introduce only a distinct model profile and packet wire
validator for source-quote preliminary classification; no new service or ledger.
TaggingSettings pins binding/model/prompt/schema/output cap. The local tagger
preflight explicitly recognizes the preliminary profile only with the current
SYSTEM_PROMPT; its separately pinned settings cannot be exchanged for element
settings. The inherited element transport still rejects the preliminary profile.

No API/DB/schema migration in this adapter step. Existing compact-wire and receipt
identities remain unchanged; the new transport records its own version. Raw
responses must still pass validate_preliminary against the trusted original graph.
Neither a transport success nor a source quote proves semantic correctness.
Rollback disables new preliminary callers and preserves immutable artifacts.
The broader runtime snapshot changes are not enabled before their separate
compatibility/rollback and source/authorization contracts are implemented.

Progress: preliminary wire transport implemented with distinct pinned settings,
literal source quotes, source-packet hash validation and inherited durable call
receipts. Coordinator strengthened malformed-envelope tests to recompute the
packet digest, proving rejection beyond a stale-hash check. Product runtime
integration and source-aware authorization composition remain incomplete.

## Runtime review decisions

The independent review confirmed the blocking guards in RunService, local
runtime configuration, run/tag stores, LocalTagRunner and review editing.
Implementation must pin three distinct uses: extraction, preliminary and element
tagging. Reuse TaggingSettings for the latter two; do not add a duplicate settings
class or treat one extractor approval as authority for all calls.

Do not adopt the review's proposed UTF-8-byte-count-plus-500 token ceiling: its
chat-framing upper bound is unproved. A validated counter or explicitly specified
conservative capacity-reservation contract is still needed. Actual provider usage
must be retained separately from any pre-call reservation.

Candidate-only processing must leave grades absent for an unapproved rulepack.
Both initial publication and later human tag editing need that guard; setting
`RuleContext.local_synthetic=True` for a real provider is forbidden. The existing
`extraction_reference_only` snapshots keep their old extraction-only meaning.
New candidate-tagging semantics need an explicit additive contract and rollback,
including live extractor/preliminary/element composition, rather than requiring
fabricated domain approval or silently changing old snapshot meaning.

## Live tagging checkpoint — 2026-09-19

Direct ordinary Codex quota read: 69% used / 31% remaining. No new paid product
calls during this checkpoint. Focused runtime configuration, live transport,
capacity policy and review tests: 106 passed (two existing deprecation warnings).
Ruff check/format: passed, 318 files. Mypy: passed, 180 files; untyped function
bodies retain the existing coverage limitation.

Found and fixed a configuration authorization gap: independently valid preliminary
and element settings could be exchanged between pipeline roles. A regression test
first reproduced acceptance; explicit profile-role validation now rejects it.
Added checks that disagreeing preliminary replies or repeated provider IDs never
form consensus, while retaining all three actual usage records. Unapproved live
rulepacks return RULEPACK_APPROVAL_REQUIRED before human resolution can publish a
grade; the review service test verifies unchanged revision history.

Next blocking integration defect (not resolved by those tests):
LocalSQLiteReviewStore.publish_transaction still explicitly rejects every
non-synthetic RuleContext. The new live worker therefore cannot yet publish its
candidate review end to end. Extend this boundary using the immutable authorized
run snapshot and matching source/settings/receipt pins, not by simply removing
its synthetic guard. Add real-mode worker publication/reopen and cancellation/
incomplete-receipt recovery tests before attempting the bounded real-PDF pilot.
The focused review-service test is not evidence of live review-store publication.
The whole pipeline remains incomplete; no service-readiness or accuracy claim.

### Review publication boundary follow-up — 2026-09-19

The unconditional synthetic-only publication rejection has been replaced for
explicit live runs with immutable run-snapshot validation. The store checks the
snapshot hash, tenant/run/document/source identity, complete rulepack hash,
settings/runtime policy pins (existing tagging_settings validator), each receipt's
real marker and model/prompt hashes. Candidate-reference runs cannot save a
decision. No new table, external API call, or domain approval was introduced.

Local review persistence fixtures verify publish, idempotent re-publication,
reopen, and rejection with no review head written for missing snapshot, source,
mode, snapshot hash, synthetic receipt, model and prompt mismatches. These are
controlled persistence fixtures, not real-provider quality or end-to-end evidence.
The initial publication fixture also caught JSON tuple/list representation drift;
rulepack identity now compares canonical hashes rather than Python containers.

Validation: combined focused suites 133 passed before two additional model/prompt
negative cases; final publication suite 8 passed. Ruff check and format passed
(319 files), mypy passed (180 files), architecture verifier passed. Whole suite,
builds, real-mode worker publication/recovery and bounded actual PDF pilot remain
pending for this uncommitted live-tagging branch. Next action: genuine run-created
snapshot → parse/extract checkpoint → live-mode fake-HTTP worker → review replay;
then real provider pilot only after those transactional checks pass.

### Worker-to-review integration — 2026-09-19

OpenCode Muse Spark 1.3 Free task task_48d6e6eceeae / ctx_d605146b813e drafted
an integration test but exhausted free quota (visible retry ~6h37m) before
validation. Coordinator interrupted retry, exited the agent to a confirmed shell,
abandoned the unfinished dispatch, released and closed its external terminal;
then corrected and ran the test. No active worker/editor remains for this task.
This is coordinator-completed work, not a successful worker report.

The test now creates an actual RunService upstage_local snapshot and SQLite
registry, runs parse/extract/tag workers, publishes candidate review, reopens
and replays it without another HTTP request or another billed attempt. Source
verification/native provenance and all provider HTTP replies are explicit test
fixtures; this is transactional integration evidence, NOT real-PDF/model accuracy.
It makes 1 fake extractor call + 3 preliminary + 3 element calls, with distinct
receipts and no grade under the unapproved rulepack.

Integration found two defects missed by isolated fixtures: registry metadata is
nested MappingProxyType, which artifact_sha256 previously could not serialize;
and review publication must check the classification-appended prompt hash, not
just the base prompt hash. The shared registry JSON encoder now supports Mapping
without changing ordinary JSON hashes; TaggingSettings.system_for_track reuses
the exact existing prompt construction for invocation and publication validation.
Also pinned checkpoint synthetic provenance and propagated LeaseLost separately
from ordinary preliminary validation failures. Tests cover incomplete receipts
(no automatic rebilling) and lease loss before/during a call.

Validation: full suite before the final registry/prompt corrections: 2424 passed,
7 skipped, 2 existing warnings, 201.26s (/tmp/proofops-live-tagging-suite.txt).
After final corrections: 139 focused tests passed, including new whole worker
pipeline and publication tests. Ruff check/format (320 files), mypy (180 files)
passed; doc/contracts 823 checks, license gate, all four Python builds and web
type/build passed during this checkpoint. A full final-tree rerun remains needed.
Codex direct quota: 70% used / 30% remaining. No paid product calls this wave.

Next: verify crash-after-publication rollback and interrupted worker recovery
with this real-mode harness; final-tree checks; extend explicit pilot config for
separate preliminary/element bindings and run a bounded actual PDF pilot against
the original USD20 ledger. Relationship tags remain unresolved (empty supplier),
so this is still not a complete service or a claim of measured model accuracy.

### Actual PDF/model pilot — 2026-09-19

Added bounded --live-tagging / --tagging-max-calls options to the existing local
pilot. No new ledger or allowance. Rollback/crash-after-publication and before/
inflight cancellation tests pass on the real-mode worker with fake HTTP.

Two fresh actual KB physical-page-30 runs used native source verification,
Solar Pro3 extraction and Solar Pro4 preliminary/element transports:
- Baseline 8db23077-5360-4e86-ba6b-f79d4e6a39b5: 8 extracted claims, 6 source-
  unverified, 2 preliminary-blocked, 12 actual calls, USD0.0026942850. One claim
  had track/dimension disagreement, another returned a string dimension instead
  of the required source span. No element calls or review publication.
- Explicit preliminary output-schema run f13f7338-0e59-4f26-b3be-cf7a4374b2d9:
  6 claims, 4 source-unverified, 1 dimension-disagreement block, 1 review candidate
  published after 3 preliminary + 3 element replies. 17 actual calls,
  USD0.0130840050. One element reply failed schema validation; remaining guarded
  elements stay unknown. No grade. Not a controlled accuracy comparison: the
  extractor produced different candidates. No independent gold metric.

Evidence: evidence/live-tagging-kb-{baseline,schema}-20260919.json. Local runtime
state directories and immutable raw receipts retained. The schema run pins the
exact schema text used at creation; later $defs deduplication of the contract
file changes future settings hashes, not that stored run.
Actual candidate replay after reopening succeeded with zero additional calls;
review 12c94a2b-c859-5a65-88ac-c8ba94968e8d retains all three element receipts.
Shared ledger now 1421 calls, six pre-existing unsettled calls unchanged, total
committed/reserved USD7.9579134850 of USD20. Both pilots together USD0.0157782900.
These figures use the existing conservative price policy, not an invoice.

Validation: complete suite 2438 passed, 7 skipped, 2 existing warnings (198.83s,
/tmp/proofops-live-tagging-final-suite.txt). After adding output-schema regression:
11 focused pilot/pipeline tests passed; doc/contracts 826 checks passed. Final
ruff check/format 321 files, mypy 180 files, four Python package builds passed.
No actual cloud or deployment test. API claims/detail/cost reads were HTTP200;
a real browser review workflow remains to verify.

Next priorities: element schema failures, source-verification coverage across
additional layouts, and the missing relationship-tag supplier. Do not silently
accept non-unanimous preliminary dimensions, upgrade unverified source spans,
or equate a review candidate with established evidence. This single-page result
is useful integration evidence, not service readiness or appendix coverage.

### Rubric-aware pilot prompt — 2026-09-19

Real response inspection found the prior pilot system prompt supplied IDs but no
element meanings. One Solar Pro4 reply also used evidence catalog ID e0 in the
UUID-valued credited_from field. Keep strict validation; do not repair either
invalid credit or overbroad present assertions into accepted evidence.

Pilot settings now embed the existing config/rubric/elements.yaml ID/name,
requirement/trigger/source scopes and scope-approval state, preserving draft
status. Instructions require independent element assessment and credited_from
null (the server validates cross-claim credit). The complete prompt remains
pinned in settings/runtime hashes. No domain definition or grading rule changed.
A regression test first reproduced the missing definitions and now passes.

Actual fresh run 9dadf939-ab63-4012-90a8-a9e0eba5167c: six extracted candidates,
one review candidate; all three element replies structurally valid. Raw replies
agreed on M1 present, M2–M5 unknown, M6 not_applicable. None is an accepted finding:
relationship/context/application guards kept all unresolved and produced no grade.
This is one tagged claim, not an accuracy benchmark or a controlled A/B result.
Evidence: evidence/live-tagging-kb-rubric-20260919.json; complete raw receipts and
pinned prompt remain in .local/developer-a-live-tagging-kb-rubric.

17 actual calls cost USD0.0132523050 under the pinned conservative policy. Shared
ledger now 1438 calls, original six unsettled calls unchanged, cumulative committed/
reserved USD7.9711657900 of USD20. Focused pilot/config/transport suites: 39 passed;
ruff check/format and pilot mypy passed. Latest direct Codex quota: 71% used,
29% remaining; do not start new work at <=10% remaining.

Next: source-backed relationship extraction and explicit handling of insufficient
claim context under the frozen attribution contract, plus evaluation on another
report layout. No invented entity/metric/period, no automatic draft-rule approval,
and no loosening of source/semantic guards to inflate accepted-result counts.

### Atomic-source relation connection — 2026-09-19

Connected unanimous preliminary role spans to the real worker's relation map for
whole-block atomic claims. Previously the worker always returned an empty map,
so even fully source-bound direct evidence with all required dimensions could
never pass attribution. Existing accept_binding remains the only acceptance
checker; no domain/grade rule changed and no additional model calls were added.

Tests first reproduced the missing local binding, then a same-block subspan
leakage case. The implementation now requires exact whole-source quote/range;
it cannot reuse a partial claim's roles for other text sharing a source_id.
Complete direct numeric evidence is accepted, missing reporting period remains
undetermined, other-block evidence receives no roles, and partial atoms supply
an empty map. Existing review/replay/cancellation pipeline tests still pass.

Combined worker/pipeline/binding tests: 68 passed before one additional missing-
period parameter; final worker suite 12 passed. Ruff check/format and mypy pass.
No paid calls this checkpoint. This is only direct atomic-source reuse, not a
completed cross-source relationship supplier or new real-report accuracy evidence.
KB's partial-paragraph atoms remain unresolved as before. Follow-up must extract
roles from other candidate sources with independent literal validation and receipt
pins, then exercise other report layouts without relaxing the binding contract.
