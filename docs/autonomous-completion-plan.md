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

### Doosan body/data/appendix pilot and empty-form guard — 2026-09-19

Ran actual Solar Pro3 extraction and Solar Pro4 preliminary tagging on Doosan
Bobcat physical pages 27, 97 and 110. Source report period is 2025; visual review
confirmed climate governance prose, environmental data tables, and assurance
limitations respectively. Page 110 is only the assurance continuation, not full
appendix coverage. Source and raw receipts remain in the two new local states.

Baseline run 16942e94-c59d-4186-af4a-e4cd42746edf extracted 18 candidates; all
were blocked by source validation. Root cause at this gate: AcroForm presence
blocked all 81 paragraph blocks even though the actual form contains Fields=[]
and only default font/resource metadata. A failing regression reproduced this.
The verifier now allows only explicit empty field arrays with the conservative
Fields/DA/DR key allowlist. Missing/malformed arrays, actual fields, XFA, optional
layers and annotation appearance guards remain blocked. Native text, clipping
and rendered OCR checks still apply; empty metadata alone never verifies text.

New run 32fd0f4e-b925-42c7-ab8e-d3230712555f verified 8 source paragraphs;
52 still have clipped/rotated-word checks, 12 rendered-text mismatches and 9
native-text mismatches. This is not 8 accepted claims. Of 18 extracted candidates,
16 remained source-blocked and two assurance statements received null track from
all three independent preliminary responses. No element calls, review or grade
were produced. Model extraction incorrectly includes generic assurance prose as
environmental claim candidates; fix scope/claim classification separately without
dropping appendix evidence. Cross-source relationship extraction remains pending.

Two pilots added 22 actual calls and USD0.0062201700. Shared ledger: 1460 calls,
USD7.9773859600 committed/reserved of USD20; the original six unsettled calls are
unchanged. Evidence: live-tagging-doosan-baseline-20260919.json and
live-tagging-doosan-emptyform-20260919.json. These are development diagnostics,
not independent gold or an accuracy benchmark. Last direct Codex quota read was
71% used /29% remaining.

Compatibility: verifier source hashes change with this fix. Existing attestations
and run snapshots are not rewritten or reused under a new verifier policy; exact
replay of old native attestations requires their original code revision (0ad1cf9
for the baseline). New verifier runs use new state/manifest/receipt identities.
Rollback reverts the verifier and starts no new-policy work, preserving artifacts.
Focused native verification tests: 14 passed; targeted Ruff check/format and mypy
passed. Documentation/contracts validator: 831 checks passed (not app evidence).
Full application regression results are recorded after the running suite settles.

Final regression for this checkpoint:
`uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`
→ 2448 passed, 7 skipped, 2 existing deprecation warnings, 190.88 seconds.
Log: /tmp/proofops-emptyform-full-suite.txt. The E2E scope here is the staging gate;
real browser review and cloud runs remain not_run. No active paid calls remain.

### Environmental claims versus assurance prose — 2026-09-19

Changed only the real extractor prompt to distinguish company environmental
claims from an assurance provider's engagement scope, procedures, limitations,
exclusions and responsibilities. Actual company environmental claims remain
eligible in appendix material and when mentioning assurance. No blanket page or
keyword exclusion and no change to evidence retrieval or grade rules.

A same-input comparison reused the eight retained Doosan source packets and ran
one new Solar Pro3 response per packet under the new pinned prompt. The three
assurance-only packets went from six claim candidates to zero. Eleven complete
body claims in four other packets were preserved verbatim. The remaining input
starts mid-quotation (a parser fragment); its new full-fragment response failed
the existing paired-quotation validator and was retained as failure, not counted
as a successful empty result. Initial evaluation stopped on this failure; resume
loaded both existing receipts and called only the six unprocessed packets. No
failed/incomplete request was retried. This is an assistant-reviewed development
comparison, not independently labeled accuracy. Evidence:
`evidence/extraction-assurance-ab-20260919.json`.

Eight real calls cost USD0.0012429450; cumulative shared commitment/reservation
is USD7.9786289050/20, 1468 calls, original six unsettled unchanged. Focused
extractor/pilot config suite: 42 passed. Ruff check/format, targeted mypy and
proofops-agent package build passed. Previous full suite (2448 passed) predates
this prompt change; the focused suite covers its runtime/profile contract.
New prompt hash requires new run settings; immutable earlier runs are unchanged.

Investigated the Doosan paragraph coordinate failure using the already present
native_word_ink_geometry module. The original pdfplumber font boxes for the
preceding heading overlap the body rectangle although PDFium glyph ink boxes
are wholly above it. This is a font-metric discrepancy, not a justification for
widening the clipping tolerance. Diagnostic evidence is saved in
`evidence/doosan-paragraph-geometry-20260919.json`; no source was promoted by it.
Next: source-bound glyph selection plus rendered agreement under an explicit
pinned policy, retaining hidden-text/overpaint/clipping rejection and old receipts.

Ordinary Codex quota: 72% used /28% remaining. Antigravity.app and Antigravity
IDE.app are installed, though antigravity is absent from PATH; absence of the
CLI is not evidence of exhausted Antigravity credits. OpenCode's previous free
usage rejection remains recorded. No worker or paid request is currently active.

### Glyph-based source verification and multi-section tagging boundary — 2026-09-19

Implemented the documented native glyph verification policy using the existing
Unicode+origin mapping adapter. Font mode remains the standalone v1 default;
the explicit worker --verify-paragraphs path now pins paragraph_native_glyph_v2,
the glyph verifier hash, and a v2 immutable attestation. It selects tight glyph
boxes, checks intersecting word containment and exact native text, then requires
rendered crop OCR agreement. Unmapped words intersecting a crop block it; unmapped
navigation elsewhere remains recorded without blocking all other paragraphs.
All actual hidden/overpaint tests now run in both modes. Existing strict font-box
clipping tests remain unchanged. No table or semantic-evidence approval is added.

Actual Doosan glyph validation: 19 verified paragraph blocks (including labels),
26 clipped/rotated, 18 rendered mismatches, 14 native mismatches and 4 unresolved
glyph mappings. The 173 non-paragraph blocks still require relationship/table
validation. The first whole-page-completeness experiment verified only 5 blocks;
localized unmapped-word handling was then tested explicitly before final delivery.
Standalone artifacts remain in .local/developer-a-doosan-glyph-verification and
.local/developer-a-doosan-glyph-crop-verification. Neither rewrites old attestations.

New actual pipeline run 6e650d77-da87-465a-9c99-54dd20ba07e5 (same physical pages
27/97/110, new manifest and settings) extracted 11 claims, with 8 source-blocked
and 2 preliminary-blocked. One candidate review was durably published, but its
three element attempts failed: first PROBE_REQUEST_TOO_LARGE, then the transport
stop fence. The shared probe request-byte ceiling prevents the multi-section
packet plus rubric prompt from being sent. Do not count this as element-tagging
success. Next resolve that bounded wire-size/packet-budget mismatch, retaining
full receipt and evidence-scope semantics, then retest the same multi-section flow.

15 real calls (8 extraction and 7 preliminary) cost USD0.0056413500. No successful
paid element call. Shared ledger is 1483 calls, USD7.9842702550/20 committed or
reserved, original six unsettled unchanged. Offline review-input replay passed
with zero additional calls. Evidence: live-tagging-doosan-glyph-20260919.json.

Final native source suite: 24 passed. Full unit/contract/acceptance/integration/
security plus staging-gate suite: 2458 passed, 7 skipped, 2 existing warnings,
189.29 seconds (/tmp/proofops-glyph-full-suite.txt). Ruff, targeted mypy and
proofops package build passed. Actual browser review/cloud still not_run.

Antigravity discovery: the installed IDE exposes
/Applications/Antigravity IDE.app/Contents/Resources/app/bin/antigravity-ide;
its documented chat subcommand accepts ask/edit/agent sessions in the UI. This
is not yet a supervised Orca worker or proof of model availability/credit. No
Antigravity task was dispatched and no Codex fallback worker was fabricated.

### Bounded coverage wire and early request-size gate — 2026-09-19

The previous failed element request had 6505 UTF-8 system bytes and 11936 user
bytes; about 10KB was the unprocessed-source UUID inventory, not evidence text.
Added opt-in upstage-compact-coverage-unicode-v2: only those omitted/unprocessed
ID lists become counts plus canonical hashes on the model wire. Original logical
request/IDs stay in receipts, all evidence content stays intact, and not-found
remains unknown. V1 wire/profile remains supported unchanged. The pilot opts into
new profile/settings/runtime hashes; no old snapshot is rewritten.

Extracted the existing probe request-body validation into one shared method and
call it during input counting as well as dispatch. The exact existing 16KB JSON
wire ceiling is now checked before run token reservation or receipt creation.
USD20 ledger policy and per-call reserve are unchanged. Regression tests first
failed for unsupported v2 and missing early oversized rejection, then passed.
Focused transport/preflight/pilot/run-config suites: 95 passed. Full application
suite plus security/staging gate: 2460 passed, 7 skipped, 2 existing warnings,
189.45 seconds. Ruff check/format, five-file mypy, proofops and agent builds pass.

Actual new run 4b92e9dd-cdb4-41fb-9d59-700b028b3ab8 used Doosan pages 27/97/110.
It extracted 12 candidates; the source-verified claims all stopped at preliminary
validation/consensus (a non-literal metric quote, a string instead of quote ref,
and differing metric spans). Therefore this run produced no element invocation
or review: the new wire profile has test evidence, but real provider element
success remains unverified. Do not rerun until sampling produces a convenient
success; improve the source-bound preliminary contract from these retained cases.
Evidence: live-tagging-doosan-coverage-20260919.json, raw receipts in its state.

17 actual extraction/preliminary calls cost USD0.0069577200. Shared ledger:
1500 calls, USD7.9912279750/20 committed/reserved, six original unsettled calls
unchanged. No paid process remains live. Next: prevent preliminary quote/schema
errors with a bounded source-selection representation while preserving literal
validation and uncertainty, then re-exercise cross-section element tagging and
cross-source relationship extraction. Browser flow and independent gold remain
outstanding; full goal is not complete.

### Preliminary role examples and controlled replay — 2026-09-19

Kept source/schema validation and the three-response consensus requirement strict.
Added small generic management/performance examples to the preliminary prompt:
management activities need not have a metric, literal numeric indicator phrases
use {source_index,quote}, and any non-literal/repeated/wrong-role quote must be
null. No company-specific fix, automatic repair, majority relaxation or grade
rule change. Examples use a fictional company, not a report-derived gold label.

Ran one new three-call ensemble for each of the exact three verified Doosan
claims that failed in the previous coverage pilot. All 9 responses passed the
existing literal/schema validator; each claim's three classifications/dimensions
agreed. Metric remained null for management prose; missing entity/period was not
invented. This is an authorized standalone development diagnostic, not a new
pipeline approval or independent accuracy metric. Original packets/responses
and new packets/responses remain immutable; failures were not retried until pass.
Evidence: preliminary-examples-ab-20260919.json. Nine calls cost USD0.006315210.

Official reference inspected: UpstageAI/Solar-Pro4-Cookbook README capability
guides describe schema-in-prompt/null handling and few-shot classification
(https://github.com/UpstageAI/Solar-Pro4-Cookbook/blob/main/README.md).
This does not establish provider-enforced JSON Schema for our chat endpoint;
no unsupported response_format parameter or enforcement claim was introduced.

Post-change preliminary/transport/config suites: 77 passed; live worker/pipeline/
preflight suites: 51 passed, 2 existing warnings. Ruff check/format, targeted mypy
and proofops package build passed. Prior full suite 2460 passed predates this
prompt-only change. Direct Codex quota now 73% used /27% remaining.

Actual pipeline follow-up run 464650a9-350a-468e-8ee1-e3944a73eaee used new
settings/state with the same Doosan pages and a bounded 18-call tagging limit
(to permit three independent 3+3 ensembles). All 9 preliminary and 9 element
responses completed; element schema validation passed for all 9. Three immutable
candidate reviews were published. All elements remain guarded unknown because
attribution/applicability is unresolved; no grade was computed. Nine other claims
remain source-blocked. This confirms actual v2 wire/provider integration, not
semantic evidence acceptance. One saved review replayed with zero additional calls.

26 calls including extraction cost USD0.0209566500. With the standalone comparison,
shared ledger is now 1535 calls, USD8.0184998350/20 committed/reserved, original
six unsettled unchanged. Evidence: live-tagging-doosan-examples-20260919.json.
Wire sizes and immutable prompt/settings hashes are recorded there. All paid
processes have settled; full source coverage, cross-source binding supplier,
independent gold, browser integration and human rule authority remain outstanding.

### 2026-09-19 · Offline attribution blocker audit (no paid calls)

PR #6 CI is now green for all six checks, including supply-chain (run
35381481660). Direct Codex quota remains 73% used /27% remaining. This is CI
completion, not evidence that the model's claims are substantively accepted.

`evidence/audit-live-tagging-blockers.py` reads the original SQLite stores in
read-only mode, selects the checkpoint by the run's committed SHA-256, checks
frozen packet hashes and compares stored raw/guarded replies. Reproduce with:

```
uv run python evidence/audit-live-tagging-blockers.py \
  .local/developer-a-live-tagging-doosan-examples \
  .local/developer-a-live-tagging-kb-rubric
```

Recorded output: `evidence/live-tagging-blockers-20260919.json`. This checks
stored artifacts, not PDF geometry, independent semantic truth or full replay.
It does not modify old revisions, call a model or change source/binding approval.

Observed blockers (counts are replicate-element votes, not independent claims):

- Doosan: all 33 raw `present` votes became `unknown`; all 33 cite sources with
  no supplied relation roles. All three reviewed claims lack a reporting period
  and metric; two also lack an explicit entity. Nine other claims have no review.
- KB: all three raw `present` votes became `unknown`; all lack supplied relation
  roles. Its one reviewed claim lacks a reporting period. Five claims have no review.
- Independently, 20/33 Doosan and 3/3 KB raw `present` votes provide a non-null
  normalized value unequal to every full cited quote after NFC/whitespace
  normalization. This is an additional guard condition, not the observed first
  rejection: binding short-circuits first. Fixing only role delivery would not
  make these outputs accepted.

The root paths are separate and must not be fixed by filling invented facts:

1. `tag_runner.py` only obtains relation roles from preliminary output, before
   retrieval. Partial-atom roles are intentionally not attached to an entire
   source block; all four reviewed claims have an empty relation map. Add
   source-span-specific relationship extraction/validation after retrieval,
   with immutable settings, literal references, authorization and bounded calls.
   Do not simulate a separate claim for each candidate or spread one atom's roles
   across its whole paragraph. Cross-source entity/period/metric conflicts must
   continue to reject and unresolved axes must remain explicit.
2. `accept_binding` requires entity, metric and period before its local-claim
   branch, including M1/M4. Original v2 §4.4–4.5 names management implementation
   and boundary criteria without making a quantitative metric/date universal;
   Master §5 still requires typed attribution. An applicable-axis/local-atom
   contract is needed, with adversarial multi-entity/multi-year examples, before
   altering acceptance. Missing fields are not blanket permission to bypass
   attribution. No new interpretation or domain approval is claimed here.
3. Compact evidence IDs restore the whole catalog SourceRef; the current pilot
   prompt does not explain that a non-null normalized value must equal one full
   restored quote. A short name/summarization therefore fails the service's
   literal-value guard. For qualitative elements, a truthful null can preserve
   evidence without inventing a value; numerical elements require an exact value
   span. Fix the wire contract/prompt together, retaining old transport profiles
   and immutable receipts. Validate with the same saved packets, then measure
   real responses; do not relax exact-source checks to accept paraphrases.

These observations change the next action: additional full PDF/model retries
without resolving role delivery and the compact-value contract will not solve
this bottleneck. No product acceptance or accuracy improvement is claimed for
this diagnostic step.

Validation: two executions of the offline audit were byte-identical; Ruff check
and format passed. Existing binding/tagging acceptance suites: 107 passed in
3.64s (`/tmp/proofops-blocker-contract-tests.txt`). These tests verify the current
contracts; they do not resolve the observed real-report blockers. No production
runtime/prompt behavior was changed by this audit.

### 2026-09-19 · Exact quote transport implemented and exercised

New opt-in `upstage-compact-source-quotes-v3` lets the model select an exact
unique subquote inside an existing evidence catalog entry. The server reuses
`UpstageClaimExtractor._locate`, preserves provenance and enclosing bbox, and
restores offsets. v1/v2 behavior and existing receipts remain unchanged. New
local pilots use v3; source verification, normalized-value equality, attribution
and rule authority are not relaxed. This addresses the compact-value bottleneck,
not the missing relationship supplier or applicable-axis contract.

Eight new cases failed before implementation (unsupported profile). Transport
and downstream guard tests now confirm valid Korean subspans, malformed/absent/
ambiguous quotes, no invented offsets, missing-role unknown, and replay without
new calls. Full suite: 2471 passed, 7 skipped, 2 existing warnings, 185.16s
(`/tmp/proofops-quote-profile-full-suite.txt`). Ruff check/format, targeted mypy,
proofops build and documentation/contract validation passed. No dependencies,
public DTOs, migrations or domain grading rules changed.

Actual run `60d9f9c0-b9b8-49d7-a790-e417763a2ac6`, Doosan pages 27/97/110:
12 extracted claims, 9 source-blocked and 3 candidate reviews; 8 extraction,
9 preliminary and 9 element calls. All 9 element responses expanded successfully.
Of 31 raw present element votes, 2 violate literal normalized-value equality;
all 31 remain unknown because relationship roles are unavailable. In the prior
v2 run this condition appeared in 20/33 votes, but fresh extraction/model replies
mean this is not a controlled A/B or an accuracy estimate. M2/M5 in replica 1
of one claim still summarize a whole selected sentence rather than selecting
the value span, and M2 semantics require separate evaluation. No grade exists.

One immutable review replayed successfully with zero additional calls. Pilot
cost USD0.0227965650. Shared ledger: 1561 calls, USD8.0412964000/20 committed/
reserved, original six unsettled unchanged. Evidence with raw expanded replies,
request/wire/response hashes, blocked-vote audit and replay is in
`evidence/live-tagging-doosan-quotes-20260919.json`. All invoked processes settled.
Direct Codex quota: 74% used /26% remaining. Cross-source relationship extraction,
management applicable-axis attribution, source coverage, independent gold and
service release gates remain outstanding.

### 2026-09-19 · Preserve roles within atomic claim spans

The live preliminary stage no longer drops every partial-paragraph role map.
After the same three independently validated replies agree, `local_relation_tags`
retains roles under source_id:start:end keys. Both automated tagging and human
review use one `relation_tags_for` resolver: exactly one containing scope, no
role escaping that scope, no whole-source fallback once scoped keys exist.
Old source_id-only maps preserve their behavior and stored revisions are not
rewritten. The guarded-cache version is now tagging-010-v2-source-spans.

This is a prerequisite for safe attribution, not the cross-source supplier.
Null metric/period/entity values remain null and all original binding guards
still apply. No domain applicability interpretation has been introduced.

Real saved Doosan review replay: its claim occupies characters 0..71 of a
233-character paragraph. The previously discarded literal entity span 43..47
("두산밥캣") is retained for that atom by the new shared helper; the whole parent
paragraph cannot borrow those roles. Metric and period remain null, so M1
binding stays undetermined and the decision remains null. Original review inputs
are unchanged and replay made zero additional model calls. Evidence:
`evidence/local-relation-scope-replay-20260919.json`.

Five scoped-lookup cases failed before implementation. Binding/tagging/live-worker
checks: 124 passed. Human-review tests: 32 passed, 2 existing warnings; positive
scoped reviews create a new revision while out-of-span edits return 422 with
BINDING_REJECTED and do not change stored history. The test fixture initially
patched a separately imported module instead of the executing fixture; corrected
the fixture target, not the production guard. Existing offline audit output for
both earlier Doosan/KB runs remains byte-identical after switching its lookup
to the shared resolver. Ruff check/format, targeted mypy, build and package
contract validation passed. Full-suite result is recorded after completion.

Full local suite completed: 2478 passed, 7 skipped, 2 existing warnings in
180.68s (`/tmp/proofops-span-roles-full-suite.txt`). Codex remains 74% used /26%
remaining. No paid calls were made; shared ledger remains USD8.0412964000/20.

Separately, prior-head CI 35383808290 completed with one failure in
`test_opt_in_publishes_v4_and_replays_immutable_receipt`: parser returned failed
instead of committed, with no useful root error in the existing assertion.
Its supply-chain audit steps passed; failure was in the job's integration-test
step (2237 passed, 1 failed, 1 skipped). Local success does not resolve this Linux
CI failure. Capture underlying immutable job/attestation diagnostics before
claiming a fix; do not weaken replay equality or retry until a green result.

CI diagnostic follow-up: the failing worker test now retains the real attestation
outputs and committed job error in its assertion message. No exception is
swallowed, source status changed or assertion relaxed. The original attestor and
replay still run. Native-worker suite: 12 passed locally, 2 existing warnings,
43.09s; Ruff check/format passed. This is failure instrumentation, not a claim
that the intermittent Linux failure is fixed.

### 2026-09-19 · Direct local attribution separated from cross-source joins

Orca review task task_30c1f60f1646 / dispatch ctx_533c1ee5d514 used the requested
fallback Codex gpt-5.6-terra, medium (requested/effective/provider matched). The
read-only worker cited original v2 §4.1/4.4/§6 and found that a mandatory literal
entity/metric/reporting-period triple for every local claim is an implementation
inference, not an explicit domain requirement. Coordinator independently checked
those passages. The worker made no edits or API calls, reported succeeded, and
was released/closed before acknowledgment; no reclaimable worker remains. This
is technical review, not human domain approval or gold-label authority.

`accept_binding` now distinguishes verified literal containment in the same
atomic claim (only when the element allows local_claim) from joining another
paragraph/table/appendix source. Local identity does not require the three join
keys; it does not populate missing fields. Every supplied role is still checked,
including when its counterpart is absent. Conflicts, invalid periods, forged or
out-of-claim roles fail. Explicit unknown additional axes still block. A scoped
role resolver now returns None for a known unresolved scope, distinct from an
empty map for unprovided roles, so local identity cannot bypass the scope guard.
Other-source requirements and numeric/year global prohibitions remain unchanged.
No grading rulepack or source quality approval changed. Guarded-cache version:
`tagging-010-v3-local-identity`; old reviews keep their stored guarded results.

Four new local/forged-role cases failed before implementation. Tests of the old
blanket local join requirement were replaced with explicit direct-local versus
cross-source cases; original product-null, forged evidence, other-year/product,
scoped-review rejection and unresolved-source assertions remain enforced. Added
local role-conflict/invalid-period checks. Full local suite: 2484 passed, 7
skipped, 2 existing warnings, 196.82s. Ruff check/format, targeted mypy, build and
package contract validation passed. Logs: /tmp/proofops-local-attribution-*.

Saved Doosan review replay preserves the original unknown review, but evaluating
its same validated 0..71 atomic claim under the new pure binding function now
accepts local M1 attribution. Entity remains literal; metric/period remain null;
the 233-character parent cannot borrow its roles. This component replay creates
no revision or grade. Evidence: local-direct-attribution-replay-20260919.json.
An initial diagnostic's global ledger-count assertion raced the separate KB paid
run; it was rerun only after that process settled. No model retry was performed
by that offline diagnostic, and the serialized rerun used zero additional calls.

CI for the preceding diagnostic head a51252f (run 35385082818) completed all six
checks successfully. The earlier intermittent native-worker failure was not
reproduced; its underlying cause is still unproven. Do not call it fixed based
on one successful run. The improved failure receipt instrumentation remains.

Actual KB follow-up (same physical page 30, fresh declared-subset run)
`b5857267-1b2c-4df7-a818-2ddf67d4094e`: 6 claims, 4 source-blocked, 1 preliminary
unresolved, 1 candidate review. The literal named means "녹색채권 관리체계" is M1
present in all three guarded element replies. Nine other raw present votes remain
unknown for literal-value mismatch. No grade or rule approval exists. This is a
successful component/pipeline example, not independent semantic accuracy or full
report coverage, and fresh extraction prevents treating earlier KB runs as a
controlled A/B. The published review replayed with zero additional model calls.

17 actual calls cost USD0.0106203900. Shared ledger: 1578 calls,
USD8.0519167900/20 committed/reserved; original 6 unsettled unchanged. All paid
processes settled. Evidence: live-tagging-kb-local-attribution-20260919.json.
Remaining major work includes cross-source relationship extraction, semantic
false positives/value-format errors, source/table coverage, independent gold,
and human rule/deployment authority. The full goal is not complete.

### 2026-09-19 · M3 framework-name semantic correction (bounded evaluation)

Observed baseline: KB page30's green-bond framework sentence was labeled M3
present in three raw replies, although it states allocation under a framework,
not external verification. Literal-value guards previously rejected those votes;
that formatting rejection must not be mistaken for semantic correctness.
The pilot prompt now distinguishes named means (M1) from an explicit external
verification action (M3), with fictional contrasting examples. No new required
provider-name/assurance-level fields, keyword guard, grading rule, or source
approval was added. P4 assurance coverage remains distinct. New runs receive
new prompt hashes; old reviews are immutable.

Actual fresh subset run `56c9ff6e-5cda-4448-8164-1c0c63bff89c`: 6 extracted
claims, 4 without review, 2 candidate reviews; 20 model calls, USD0.0142553400.
For the exact framework sentence, all three raw and guarded M3 states are
unknown; M1 remains present in all three. Two M3 unknown responses still attach
an irrelevant page heading. M2 present and one M4 present are NOT independently
validated domain truth. A different claim has one LLM_SCHEMA_INVALID response.
Fresh extraction means this is not a controlled same-packet A/B or an accuracy
benchmark. No grade was produced. Raw/guarded replies and provenance are in
`evidence/live-tagging-kb-m3-prompt-20260919.json`.

A standalone fictional positive/negative diagnostic stopped on its first
Upstage HTTP400. No response was validated, no automatic retry occurred, and its
USD1 reservation remains in the original ledger. Positive-case sensitivity is
not established. Total ledger: 1599 calls, USD9.0661721300 committed/reserved of
USD20, 7 unsettled (the original 6 plus this request). Do not refund/reset these
reservations without provider reconciliation. The API error's root cause is
unproven; product pipeline calls in the separate run succeeded.

Read-only semantic review: Orca task task_af5d4263faa9, dispatch
ctx_793dd23fe5af, effective gpt-5.6-luna, medium; succeeded and released before
acknowledgment. It supports the M1/M3 distinction, not gold-label/domain approval.
Targeted pilot/transport tests were rerun: 48 passed. Earlier full2484 test
results precede this prompt-only change. CI35386799967 failed2250passed/1failed:
the native-worker failure diagnostic itself used success-only parse_job and
raised KeyError, masking the original outcome. Original worker cause remains
unproven; fixing diagnostic observability is the next bounded task.

The diagnostic repair captures the existing parse JobMessage from the pending
outbox before execution, rather than reading success-only run.parse_job after
execution. Orca task task_b50ee1fd5e54 / ctx_63a2af5f7e96 used effective
 gpt-5.6-luna medium, changed only the test, reported 12 native-worker tests
passed (44.82s), then was released/closed and acknowledged. Coordinator also
forced run_once to return failed: the original committed assertion now reports
job_error/native_attestations instead of KeyError. Ruff check/format and
 git diff --check passed. This repairs failure observability; the intermittent
original native receipt failure still requires evidence from CI.

### 2026-09-19 · Immutable M3 review replay and transport failure diagnosis

The new KB framework claim review loaded successfully through the actual local
composition with UpstageProbe.complete replaced by a failing sentinel: no model
call can occur in that check. This verifies saved-review reconstruction, not
semantic accuracy. Evidence: live-tagging-kb-m3-replay-20260919.json.
The other claim's invalid response contains a 40-character packet_sha256 rather
than its actual frozen packet hash. The schema/identity guard correctly rejects
it; stored responses were not repaired. A future versioned compact transport can
remove model copying of server-owned identities, while retaining request/packet
hash verification and immutable receipts. No v1-v3 transport behavior changed.
The live runtime was also traced: preliminary() returns only local_relation_tags,
then tag_runner retrieves other evidence but passes the same local map. Separate
literal role extraction after retrieval remains required for cross-source joins.
CI35388220142 at head18a563b still has its supply-chain integration step running;
all five other jobs passed. No duplicate CI/model run was launched.

### 2026-09-19 · Literal cross-source role validation foundation

CI35388220142 for18a563b finished successfully: all six jobs passed. Linux
acceptance/integration:2251passed,1skipped; unit/contracts/staging-gate:232passed,
7skipped. This does not establish the root cause of the earlier intermittent
native-receipt failure; its diagnostic repair remains in place.

Added application/tagging/relations.py: build a source-indexed request from
verified whole canonical refs and validate exactly one dimensions map per source.
Required entity/metric/reporting_period keys, literal unique quotes, nulls,
provenance and all supported axes are retained. Partial/duplicate scopes, foreign
identity, unverifiable sources, malformed selectors, missing/duplicate rows and
grade fields are rejected. The existing preliminary literal-span parser is
reused; its strict v1 offsets and v2 unique quotes remain compatible. No evidence
Claim is fabricated, no provider is called, and the module does not grant binding
or grade authority. Runtime integration is still pending, as explicitly specified
in docs/local-live-tagging-runtime-contract.md.

Orca task task_a25233efa853 / ctx_1cc64c44c6c0, effective gpt-5.6-terra medium,
reported115 related tests passed, then was released/closed and acknowledged.
Coordinator review caught type-before-access and duplicate-index issues, which
were corrected before acceptance. Coordinator then strengthened source-hash
assertion from length-only to exact restored-reference hash equality, changed
the positive binding test to use an actually different table cell, added a
wrong-row role borrowing rejection, and covered tenant/offset/required-role
failures. Do not treat an agent report as broader test coverage than its code.
Before the final four negative cases,155 targeted acceptance/transport/worker
checks passed. Final full local suite:2507passed,7skipped,2existingwarnings in
183.99s (/tmp/proofops-relations-full-suite.txt). Ruff check/format, targeted mypy,
architecture validation, proofops build and package documentation/contracts checks
passed. No additional model calls occurred in this implementation.


### 2026-09-19 · Optional live relation runtime and actual pilot

Connected the source-relations-v1 validator through a separately authorized
Upstage relation profile, optional frozen configuration/pins, source-stage receipt
recovery and a three-replica worker stage before element tagging. Reuses the
existing transport and source-replica loop. Only whole verified references already
in the retrieval packet are eligible; local claim roles retain precedence.
Incomplete or disagreeing relation responses block this claim without assigning
absence. Existing snapshots without the optional group retain their old path.
Pilot opt-in: --live-tagging --live-relations; the tagging cap includes all stages.
No HTTP/DB migration or new dependency. Disabling the option requires a fresh run;
existing immutable revisions and receipts are preserved.

Orca transport task task_9b4aaa27e28e (Terra) and configuration task
task_ebea57653f7d (Luna) completed and were released/acknowledged. Coordinator
review reproduced and corrected two faults before acceptance: the relation wire
must retain the rendered JSON schema instructions, and extraction-only mode must
reject supplied relation settings rather than silently ignore them. Additional
checks cover profile/prompt/model/grant mismatches, optional pins and immutable
replay; the synthetic pipeline exercises 18 tagger requests across two claims.

Final local validation: 2540 passed, 7 skipped, 2 existing warnings (181.53s);
Ruff and formatting passed; mypy passed for 182 source files; build passed;
package documentation/contracts validator passed 847 checks. Logs are under
/tmp/proofops-relations-runtime-*. Existing-head CI35389820972 passed, but does
not cover these uncommitted runtime changes. No broad accuracy claim follows.

Actual pilot f079a78d-7830-42c0-b7a5-094057d8d8da completed, KB2025 physical
page30: 23 provider attempts, USD0.0125277900. Six claims: four blocked by source
validation, one blocked by disagreeing relation replicas, one reached review.
All six relation replies passed literal-shape validation; one claim disagreed
on header entity/year roles and the other agreed on all-null roles. Successful
cross-source attribution is therefore NOT demonstrated. In the remaining review,
eight raw present votes became two present and six unknown; the latter six had
literal-value mismatches. This is a fresh narrow pilot, not controlled A/B or gold
accuracy. No grade emitted. Evidence: live-tagging-kb-relations-20260919.json.
Shared ledger: 1622 calls, USD9.0786999200 committed/reserved, seven unsettled
retained without reset/refund, within the existing USD20 ceiling.

Next priorities remain source verification coverage, preventing irrelevant header
retrieval, semantic element precision and representative independent gold data.
The optional relation path works mechanically but is not ready as a default:
strict whole-map agreement can block otherwise usable local evidence.


### 2026-09-19 · Diagnose the four KB source-validation blocks offline

Read the saved native attestation rather than re-running paid extraction. Three
blocked claims share paragraph7441dba9; six native words (346-350,366) fail glyph
origin matching. A direct pdfplumber/PDFium character inspection found approximately
0.17024pt horizontal disagreement after the first character in the affected spans,
versus the pinned0.001pt tolerance. The underlying font/PDF cause is not established;
nearest character is not a valid replacement for unique provenance matching.
The fourth blocked claim is a table-text paragraph: parser `녹색채권` versus native
word reconstruction `녹 색채권`. Neither case reached rendered OCR verification.
Saved source/parse/attestation hashes and exact mismatches in
live-tagging-kb-source-blockers-20260919.json. No source quality, verifier code,
normalization, tolerance or immutable receipt changed; no model calls made.
This identifies concrete blockers rather than resolving them. Next diagnostic:
trace the native width/advance disagreement and validate any correction against
ambiguous/duplicate glyph adversarial cases before creating fresh attestations.
CI35391924279 for1cd98fb remained in_progress (five jobs successful, integration
still running) at this checkpoint; poll that run rather than launching another.
Latest available Codex quota observation remained77%used at20:15UTC (not live).


### 2026-09-19 · Fix split-Tj character spacing in native glyph matching

Root cause reproduced with a minimal Helvetica PDF: with -0.17pt character
spacing, one `(AB) Tj` gives matching B origins (37.834pt), whereas `(A) Tj (B) Tj`
puts B at38.004pt in pdfminer and37.834pt in PDFium. The real KB stream similarly
splits its line after `전` and `있`; its -0.02 spacing under8.5 scaling accounts
for0.17pt. This is the pinned pdfminer between-character advance behavior, not a
reason to increase coordinate tolerance. evaluation/native_spacing_probe.py is
an independently runnable reproduction; its output is saved as evidence.

Added an isolated layout aggregator inside the existing native glyph matcher:
retain font decoding/text-state behavior, apply horizontal spacing after each
character, and retain the original word inventory/text/font boxes. Corrected
origins still require unique Unicode+origin PDFium matching at0.001pt. No global
patch, dependency, fuzzy matching, OCR relaxation or domain change. Five added
operator cases include positive/negative spacing, text arrays and empty arrays.
Red:3failed,37passed. Green:40passed including duplicate glyph, altered origin,
Unicode mismatch, page isolation and invisible-text diagnostics.

Real source/candidate/manifest/input-graph hashes were verified before creating a
fresh offline attestation. All six previously unmatched words now match (zero
unresolved words on page30). The paragraph then reaches rendered verification,
which correctly remains unresolved because OCR reads 에→어, 을→올 and comma→period.
Thus the coordinate bug is fixed but three claims remain blocked; the table
whitespace case also remains. No historical receipt or run was promoted/mutated.
Evidence: native-spacing-fix-20260919.json. New runs are required because native
policy hashes pin this implementation; rollback uses original pinned code.

Full local suite:2545passed,7skipped,2existingwarnings,185.85s; Ruff and formatting
passed; mypy183sources passed; proofops build passed; package checks passed.
Logs:/tmp/proofops-spacing-*. No additional model calls. CI35391924279 for1cd98fb
finished successfully; CI35392222827 for362420c still ran at inspection. Neither
is evidence for this new spacing correction, which awaits its own CI.


### 2026-09-19 · Rendered OCR margins: evaluate before enabling

Compared the KB paragraph at216/288/360dpi without supplying expected text to OCR;
all retained errors. Visual inspection confirmed the visible original matches
native text. Blank6px/12px borders made the216dpi crop exact;24px still missed a
comma. Evaluated fixed6px padding on73 previously readable crops across KB page30
and the saved Doosan subset: KB baseline28/36, padded29/36; Doosan19/37→20/37.
Always-padding improves four crops but regresses two, so it was rejected.

Implemented one bounded, text-blind retry only after a nonempty readable mismatch.
Already-exact reads retain their original result; empty/unavailable OCR gets no
retry. Preserve original pixels/coordinates, both readings and image hashes;
keep exact normalization and all native/source gates. Observed baseline-first
policy gives51/73 exact versus47/73 baseline (computed from the two reads, not
independent semantic accuracy). A fresh complete KB native attestation verifies
the previously blocked paragraph, retaining two OCR attempts; historical runs
and receipts remain untouched. No model/API calls or dependency changes.
Evidence: native-ocr-padding-20260919.json. Full pipeline under new code not_run.

Padding pixel-preservation test first failed; bounded-retry tests first failed
2/4, then all29 native-source tests passed. The initial full-suite attempt used
the rejected always-padding design; while it ran the verifier changed, provoking
NATIVE_PARAGRAPH_CHECKPOINT_INVALID in one test. It was stopped (2018passed,
1failed,7skipped), not counted as validation, and replaced with a fresh stable-code
suite. This local test contamination does not explain the separate Linux failure.
CI35392921961 at61f8dba: five jobs passed, native paragraph replay failed in
supply-chain (2311passed,1failed,1skipped). Root cause unproven because pytest
truncated both receipts. The test now prints an actual JSON diff on failure;
assertions and replay requirements are unchanged. Await new-head CI before
claiming cross-platform success.

Final stable-code local validation:2550passed,7skipped,2existingwarnings in205.07s.
After diagnostic-only test output changes, the targeted native-worker replay
passed separately (1passed,11.06s). Ruff/format, mypy183sources, proofops build
and package documentation/contracts checks passed. Logs:/tmp/proofops-padding-retry-*.
The full source validator still needs fresh cross-report pipeline evaluation;
no claim is made that historical blocked claims have changed or Linux CI is fixed.


### 2026-09-19 · Actual source-repair pipeline and independent replay review

Executed exactly one fresh KB page30 run at0b28f0e with original shared USD20
ledger:8833ff17-061a-4ade-8822-7bc0dc5fff50. Extraction cap8; total preliminary/
relation/element cap60 (previous cap30). All product runtime files remained frozen
through the live run. Six extracted claims, five source-verified (previous pilot
two), four immutable candidate reviews (previous one). One table-text source block
and one relation disagreement remain. Fresh extraction and different cap mean
this is not controlled A/B. No grades, rulepack approval or semantic accuracy claim.
50calls, USD0.0390675450. Shared ledger1672calls, USD9.1177674650 committed/reserved,
seven unsettled retained. Evidence:live-tagging-kb-source-repair-20260919.json.
Raw25 present element votes become13present and12unknown; all12 downgraded votes
have literal-value mismatches. Candidate review availability is not correctness.

Orca read-only review task_e663e95c2822 / ctx_c9fdde9278da ran with effective
Codex gpt-5.6-terra medium, after the previously recorded external-provider limits.
Report:/tmp/proofops-native-replay-review.md. Worker confirmed that old generic
PARSER_FAILED and truncated receipts cannot establish root cause; OCR failure
payloads and exact geometry are hypotheses until the new JSON diff is available.
No code edits, tests or model calls from this worker. Released/archived then
acknowledged delivery_b09d855aa480; no reclaimable workers remain.
Latest observed Codex quota20:56UTC:79%used,21%remaining (stop threshold90%used).


The four actual reviews reloaded successfully with UpstageProbe.complete replaced
by a failing sentinel; results are embedded in the pilot evidence. No provider
call occurred during replay. Only after replay finished was runtime edited again.

CI35393819544 now supplies decisive evidence: the only receipt payload difference
is rendered.error TimeoutExpired→CalledProcessError (plus the resulting artifact
hash), with both reads unresolved/rendered_reader_unavailable. This explains that
Linux failure: unsupported Swift Vision execution creates variable failure details
that break exact replay. The smallest root fix is a non-darwin guard before image
rendering/process launch, returning stable UnsupportedPlatform. Exact receipt
comparison and unresolved source status remain; no Linux OCR or source approval
is implied. Earlier failures are not all proven to share this cause.
Two explicit linux/win32 tests failed before the guard and31 native-source tests
passed after. Fake-render image padding test explicitly simulates supported macOS
so it exercises pixel preservation on every CI platform. No existing assertions
were removed. Source policy pins this revision; historical live run8833ff17 uses
0b28f0e for replay. Evidence:native-ocr-linux-replay-cause-20260919.json.

Final local platform-fix validation:2552passed,7skipped,2existingwarnings in193.36s;
Ruff/format, mypy183sources, build and package checks passed. Logs:
/tmp/proofops-ocr-platform-*. New-head Linux CI still required.
Additional measured service bottleneck: the actual pilot's final claims/detail
API reads took17632ms/17055ms, whereas cost read took2.9ms. Each graph read
recomputes native/OCR attestation. A future bounded cache must retain tenant,
source/graph/receipt/runtime pins and fail closed on changes; this performance
problem is recorded, not claimed fixed by source-verification improvements.


### 2026-09-19 · Reuse successful native replays for repeated reads

CI35395097962 at a3d6674 completed successfully, including Linux integration;
the unsupported-Vision guard is now verified on CI as well as local tests.

Measured/reproduced the slow read boundary before optimizing. Added a64-entry
process-local LRU of immutable verified-source ID sets, populated only after the
existing complete native replay succeeds. Read-side load_run_evidence still
validates committed pointers, source/manifest/policy and final graph hash. Key:
tenant, actual source bytes hash, entire graph/receipt hashes, native policy code
hashes, platform and reader versions. No persisted PDF/graph/receipt or new
schema/dependency. First reads, restarts, changed inputs and eviction still
perform complete replay. Parser publisher remains on the original direct path.

New test failed before the helper existed, then passed actual replay, mutated
receipt/source/tenant/graph/policy, immutable result and eviction cases. Related
native-worker tests:13passed; final eviction-enhanced focused test passed.
Actual KB native replay benchmark (fresh hash-verified offline attestation):
cold16.586s; warm0.00847/0.00786/0.00800s. This measures only the native replay
kernel, not full HTTP latency or throughput. No product model calls. Evidence:
native-replay-cache-benchmark-20260919.json.

Luna read-only review task_a8936afd3f30 / ctx_4128cfc144d7 found no required fix;
report:/tmp/proofops-replay-cache-review.md. Explicit limits:64 entries is not a
weighted memory budget; simultaneous cold requests may repeat OCR; runtime pins
are not a universal OS/font environment fingerprint. Existing parser limits and
process-local lifetime apply. No speculative distributed cache/coalescing added.
Worker released/archived and delivery_7a69c31296f3 acknowledged; no reclaimable
workers remain. New cache head still needs its own CI.

Final cache local suite:2553passed,7skipped,2existingwarnings in188.28s.
Ruff/format, mypy184sources, proofops build and package checks passed.
Logs:/tmp/proofops-replay-cache-*. No required work is inferred complete solely
from these tests; first-load latency, broader report/semantic evaluation and
remaining relation/source blockers still need work.


### 2026-09-19 · Second-report actual pipeline and full HTTP measurement

Ran one fresh Doosan Bobcat2025 pilot on physical27/97/110 at c4e85fc:
2290d163-5b61-44ac-8c16-33fffc0eaa9f. Kept report period2025 after verifying the
explicit About This Report statement on physical115. No runtime files changed
while the paid run was active. Extraction cap8, total tagging cap60. Twelve
claims: four source-verified, eight source-validation blocks; of the four, three
relation disagreements and one candidate review. This exposes limited coverage;
it is not a service-readiness or semantic-accuracy result. Raw9 present votes
became4present and5unknown (all five literal-value mismatches). All three M3
votes stayed unknown; generic DNV statement presence did not become global
assurance approval in this published review.

Actual35calls cost USD0.0216694500. Shared ledger1707calls,
USD9.1394369150 committed/reserved, seven unsettled retained. Full local TestClient
reads after the pipeline:claims197.56ms,first detail149.45ms,cost2.60ms. These are
same-process warm reads, not cold startup or deployed throughput. Evidence:
live-tagging-doosan-source-repair-20260919.json.

Visually inspected original renders27/97/110. Roles differ:governance narrative,
annual environmental metrics and assurance limitations/exclusions. Page97 shows
reporting sites39/42/54 across2023-2025, so no like-for-like trend conclusion is
inferred. Native blockers:one quote-style OCR mismatch, one middle-dot/bullet
mismatch and one crop containing adjacent heading words. Exact differences,
render hashes and scope cautions are recorded in doosan-source-visual-diagnostic-
20260919.json. No punctuation folding, crop widening or source promotion applied.
Next major limitation: relation-stage disagreement currently blocks an otherwise
verified local claim. Inspect binding contracts before considering source-scoped
uncertainty that can preserve independently supported local review elements.

Correction to the preceding validation report: CI35395921655 at c4e85fc passed
Linux supply-chain integration and four other jobs but failed Python format
check on run_artifacts.py. The earlier local format log contained the same
failure; my chained command execution masked its status and I incorrectly
reported it as passed. Corrected formatting only, then separately verified exit0
for full Ruff check, full format check (331files), and targeted cache test1passed.
The earlier2553-test result is still recorded, but was never proof of formatting.
No runtime logic changed in this formatting correction. New-head CI required.

### 2026-09-19 · Inspect relation disagreement before changing the worker gate

Extended the existing offline checkpoint auditor to include claims blocked before
review publication. It compares complete retained SourceRefs per source/axis and
preserves omitted dimensions separately from explicit null. It reports value
agreement only; provider independence, PDF geometry and semantic correctness are
not certified by this diagnostic. Runtime consensus and binding are unchanged.

Hash-verified KB/Doosan checkpoints show four relation-blocked claims (one/three),
all with three validated candidate responses. There are 7/44 differing source-axis
entries, including optional-axis omission/null differences AND substantive entity,
metric and reporting-period differences. Thus these are not merely equivalent
JSON serialization variants. Doosan responses assign 2026 in a future plan to
reporting_period and vary between committee entity/scope roles; these are semantic
review concerns, not newly approved bindings. Do not normalize missing/null or
accept a majority as a shortcut. Evidence:live-relation-disagreements-20260919.json.

Next implementation must isolate unresolved external attribution while preserving
local claim review, but retain authorization/receipt failures as hard failures.
Currently relations() returns None for both kinds; merely deleting tag_runner's
continue would conflate them. Inspect/define this distinction before changing the
pipeline, and test external refs cannot become present through fallback. No
runtime change or model call was made for this diagnosis.

Diagnostic regression failed before implementation, then 10 targeted diagnostic/
relation-worker tests passed (two existing deprecation warnings). Targeted Ruff
and format checks each independently exited0. Prior head33fbff1 CI35396684579 has
all six jobs completed successfully; last workflow-level poll was still in_progress.

### 2026-09-19 · Isolate external relation conflicts from local review

Implemented source-level unanimity after three schema-validated responses with
three distinct provider IDs. A disputed source's complete map becomes null across
the union of supplied axes; no majority, axis mixing or missing/null normalization.
All original candidate maps remain in relation_records. Existing binding rejects
unresolved external attribution while scoped local claim roles retain precedence.
Preliminary unanimity and authorization/packet/schema/receipt/provider failures
still block. Existing immutable checkpoints and public API/DB schemas unchanged;
only newly executed relation stages get the source-scoped behavior.

Before implementation, two targeted regressions failed: semantic disagreement
returned None and the real fake-HTTP pipeline blocked both claims. After the
minimal runtime change, 22 relation/preliminary worker tests passed. New pipeline
case loads published immutable inputs, proves local M1 binding accepted versus
external undetermined, retains three relation/element replicas and null decisions,
and verifies replay makes no calls (18 fake tagger calls total). No paid inference
has yet measured the resulting review coverage. Full suite/reviewer pending.

Validation:2555passed,7skipped,2existingwarnings in193.12s. Full Ruff and
format checks independently passed after correcting one test import-order issue;
mypy184sources, proofops build and package-contract validation passed. Full test
log:/tmp/proofops-relation-conflict-suite.txt. Runtime code stayed fixed throughout.
Luna task_39c3a8054ede / ctx_ea50e6a7bd71 reviewed callers/binding/recovery/cache,
found no required changes; report:/tmp/proofops-relation-conflict-review.md.
Worker settled, released and delivery_245f08e6e339 acknowledged. Actual fresh
Doosan pilot is next; fake-HTTP results do not establish real semantic accuracy.

### 2026-09-19 · Actual source-scoped relation pilot

Fresh Doosan2025 run b94cf75c-b4c5-4a36-b891-afb12a0f17b9 at35df508 on
physical27/97/110 completed with exit0. Twelve extracted claims, eight source
validation blocks, four candidate reviews. Three reviews retain disputed external
source maps (3/3/1 sources); every disputed map is null and no guarded present
citation uses those disputed sources. This checks attribution, not semantic truth.
Previous same-page run had one review and three relation blocks, but extraction
was rerun, so this is a coverage observation rather than a paired accuracy trial.
Raw42present votes became19present and23unknown;14 had literal-value mismatch.
All decisions remain null under the unapproved candidate rulepack.

Actual44modelcalls costUSD0.0379871250. Original shared ledger1751calls,
USD9.1774240400 committed/reserved, seven unsettled retained. Evidence:
live-tagging-doosan-relation-isolation-20260919.json. No code changed during the
paid run. Source-validation failures and independently labeled semantic evaluation
remain the next coverage/quality bottlenecks; this result is not production approval.
All four saved review inputs also passed fresh-process offline composition replay
with UpstageProbe.complete replaced by a failing sentinel (zero model calls).
Replay results are embedded in the evidence file. Runtime-head CI35397822041:
five jobs succeeded; supply-chain integration still running at last observation.

### 2026-09-19 · Bound the OCR punctuation repair hypothesis

Runtime-head35df508 CI35397822041 completed successfully, including Linux
supply-chain integration. No paid pilot remains live.

Added read-only evidence/probe-ocr-punctuation.py. It resolves each run's committed
parse-job artifact pointer in SQLite read-only mode, checks checkpoint hash/size
and nested receipt hash, then compares retained native/OCR strings hypothetically.
It does not run OCR, replay PDF geometry, rewrite any text/receipt, or promote any
source. Built-in adversarial checks keep decimal/minus/percent/year/negation,
Latin interior dots and prime-vs-apostrophe differences distinct.

Actual saved receipts:KB36 readable crops, zero new hypothetical matches;
Doosan38 readable crops, four new hypothetical matches (three quote-style-only,
one Hangul-interior middle-dot/bullet). Paragraph records are not claim counts:
these four potential crop matches do not establish recovery of four claims or
any measured accuracy. Evidence:ocr-punctuation-what-if-20260919.json.

Luna read-only review task_225ca8aa5787 / ctx_8917837f853f identified quote-direction,
list-marker and immutable-replay risks. Recommendation is only a versioned display
comparison until provenance/visibility policy and adversarial checks are resolved;
never change citations._normalized or native text, and clipped heading remains
unresolved. Report:/tmp/proofops-ocr-equivalence-review.md. Worker released and
delivery_32d330ecf536 acknowledged. Production verifier is unchanged. Next actual
repair should use a distinct pinned OCR-comparison contract or independent
rendered-reader evidence, not silently normalize unresolved sources into verified.

### 2026-09-19 · Independent raster OCR trial (actual external API)

No tesseract/PaddleOCR executable is installed. Used the existing bounded
UpstageParseProbe on the same original ledger instead of adding dependencies.
Four Doosan paragraphs from the punctuation diagnostic were rendered at216dpi
with6px white padding and embedded as lossless RGB/Flate image-only PDF pages.
Verified source/graph/image/submission hashes, lossless image stream roundtrip,
and zero extracted text on all four PDF pages; visually inspected the four crops.
Only raster bytes were submitted; no native text or expected transcription prompt.

One standard Document Parse call (document-parse-260128) returned a valid four-page
receipt costingUSD0.044. Exact existing-normalization comparison:1/4matched.
The CHRO paragraph containing 분석·검토 matched exactly, so independent OCR can
corroborate this crop without punctuation folding. Other3 retain quote-style or
spacing differences. These are selected failing crops, not an OCR accuracy sample.
Raw response, page/source mapping, input/image/request/response hashes and exact
diffs are retained in doosan-independent-raster-ocr-20260919.json. Input PDF and
private receipt reside at.local/doosan-independent-raster-ocr. No source quality,
claim/review checkpoint or production verifier was changed.

Shared ledger1752calls,USD9.2214240400 committed/reserved,7unsettled unchanged.
Next integration requires an explicit immutable rendered-reader receipt contract:
rebuild exact raster from original source/box, validate submission/provider/page
pins, require existing exact text equality and all native geometry checks, replay
without model calls. Do not reuse native auto-extracted PDF text as independent
visibility evidence. The failed3crops and clipped heading still remain unresolved.

### 2026-09-19 · Replay independent OCR against original pixels

Added evaluation/raster_ocr.py, reusing existing PDF/image dependencies rather than
adding an OCR stack. It constructs1..10lossless raster-only canonical paragraph
crops, binds tenant/document/manifest/graph/source/versions and validates trusted
request/receipt pins, provider identity, billing page map and unique element IDs.
No network calls and no source-quality transition; native geometry approval is
still separate. Caller pins must come from trusted immutable storage.

New regression failed on missing module, then passed original raster preparation,
byte stability, empty PDF text layer, tampered request/receipt/source/tenant,
boolean page/billing IDs, duplicate element IDs and model mismatch. A provider
transcription changing1234to1235 remains an exact-match failure. Existing original
unverified graph stays unverified throughout.

Actual saved Doosan four-page request reconstructed byte-for-byte identically.
Each crop PNG hash and source mapping also matched the earlier submitted artifact.
With UpstageParseProbe.parse replaced by a failing sentinel, saved-response replay
retained1/4exact matches and made no API calls. Evidence:
doosan-independent-raster-replay-20260919.json. This proves repeatable correspondence,
not integration into live parser promotion or semantic accuracy.

Luna review task_c27556d40dca / ctx_a3caf1f34d3c identified malformed JSON shapes,
resource limits and strict PDF geometry checks; added controlled shape validation,
200000-character total OCR text and existing1MiB raw-response caps, finite/nonboolean
page geometry and padded raster bounds. Regression reproduced AttributeError on
raw_response=null before the fix; now rejects malformed raw/usage/elements, list
mode/model, oversize text/response and NaN/infinite/boolean page widths as ValueError.
The exception previously stopped processing; it was not evidence acceptance, though
its error classification was inadequate. Review's provider-page authenticity concern
is a documented limitation: request/image reconstruction and trusted storage pins
cannot establish a provider-side per-image cryptographic attestation that the API
does not supply. Exact match is a comparison result only, not source verification.
Report:/tmp/proofops-raster-replay-review.md. Worker released and delivery acknowledged.

Final relevant suite43passed; expanded boundary regression separately passed.
Full Ruff/format(335files) passed; full mypy185sources passed before boundary changes,
and final helper mypy passed afterward. Actual four-crop byte-identical replay passed
again with paid calls forbidden. Runtime parser/attestation policy was untouched;
full app suite was not rerun for this evaluation-only helper. New-head CI required.

### 2026-09-19 · Compose native gates with exact independent raster evidence

Added experimental evaluation/native_raster_visibility.py. It first recomputes
native glyph v2 attestation, restricts selected sources to nonempty/readable
rendered_text_unresolved records, then validates independent raster replay.
Only exact matches update quality in a NEW in-memory graph. Native failures,
clipped words, mismatching OCR and forged native receipts stay excluded; original
text/coordinates/graph are untouched. Experimental proof pins both input/output
graphs, original source identity, all three evidence artifacts and policy code.
This is deliberately not a parser checkpoint reader or transport authorization.

Five regressions failed before the module existed, then passed: positive exact
corroboration, native text mismatch, clipping, external numeric mismatch, forged
native receipt. Relevant native/raster suite37passed; final proof self-hash
assertion separately passed. No paid API calls were made. Actual saved Doosan
source recomputation plus independent receipt replay yielded22→23verified source
blocks in the experimental view, retaining1/4external exact matches. These are
source blocks, not published claim results. All existing checkpoints remain fixed.
Evidence:doosan-native-raster-visibility-20260919.json.

Integration boundary identified: local_runner, job_store and run_artifacts all
validate/pin native policy and v4 publication/readback. A real integration needs
one new version across all three and explicit frozen external authorization;
adding only a reader shortcut would violate checkpoint identity and replay.

Luna review task_6b1d7f9b2400 / ctx_d272222f212a found no required bypass fix in
the composed experimental path; it reiterated that production pins must be read
from tenant-scoped immutable server storage, never accepted from caller-computed
hashes. Report:/tmp/proofops-native-raster-visibility-review.md. Worker released and
delivery_564ac836b692 acknowledged. Full Ruff/format337files and targeted mypy
passed; after the final input-shape/self-hash check, actual native/raster replay
was rerun successfully. No production verifier file or existing receipt changed.

### 2026-09-19 · Raster runtime plan and explicit image authorization

Mapped the integration across local_runner publication, job_store fenced native
policy and run_artifacts readback. Saved executable sequence in
`docs/superpowers/plans/2026-09-19-raster-ocr-runtime.md`: separate preflight,
frozen configuration/per-call checks, coordinated v5 publication/readback, then
real cross-report validation. No new cloud service or library is needed.

Implemented first gate in application/preflight.py using the existing common
local approval checks with a private document-parse branch; public extractor and
tagger gates are unchanged. Separate vision/schema/model/endpoint/mode/max-pages
binding, explicit raster-upload consent, actual document rights/source, expiry,
revocation and exact transport model hash are required. This is local-test-only;
region/live-probe remain not_run. It does not yet dispatch a raster call.

Initial19tests failed before implementation;20raster gate tests now pass including
malformed/missing rights. Combined legacy/raster preflight suite82passed before
that final extra boundary case. Full suite and independent plan/gate review pending.
Full Ruff/format338files, mypy186sources, package build and contract validator passed
independently. No API calls or ledger changes made in this step.

Full suite completed:2581passed,7skipped,2existingwarnings in188.75s. Independent
Luna review task_83e8f1c54749 / ctx_88c52ecf9888 identified integration requirements
for selected-page scope, reserved legacy fields, mode/ownership/rights/helper pins
and partial coverage. These are explicit in the plan's review decisions, not
claimed implemented by the preflight-only step. Worker released and delivery
acknowledged. Report:/tmp/proofops-raster-preflight-review.md; reviewer could not
run pytest in its shell, so its report is static review, not test evidence.

One concrete replay mismatch was fixed now: the separate raster preflight pins
an exact model, but replay inherited generic transport alias acceptance. Added a
regression showing document-parse alias was incorrectly accepted, then required
provider-reported document-parse-260128 exactly in raster replay. Generic historical
Document Parse/table adapters retain their own compatibility behavior. Added
preflight/transport constant drift assertions without reversing dependencies.
After this tightening,90targeted tests and full Ruff/format plus relevant mypy
passed. The2581full-suite count precedes this final small change; exact-head CI
still required. Actual four-page offline replay remains byte-identical with1exact
match and zero API calls. All existing source/review/checkpoint data is unchanged.

### 2026-09-19 — raster adapter/configuration checkpoint

Terra task_94073dbe7943 moved preparation/replay and visibility composition into
local adapters with evaluation compatibility exports; policy pins actual helper
bytes and installed readers. Coordinator added trusted optional RunService
configuration, Registry preflight, immutable complete policy/grant group and
store tamper rejection. A malformed grant regression reproduced AttributeError
before the shape check; the worker regression reproduced unintended legacy job
access before the explicit unsupported-runtime guard. Both were fixed without
changing existing native/semantic verification. This is partial plan step 2;
per-call authorization, v5 publication/readback and rollout trials remain open.

Focused coordinator suite:35passed. Independent Luna task_e9ec54a38dd2 /
ctx_b7dd4025900b found no actionable defects and ran38configuration/preflight
tests successfully; report /tmp/proofops-raster-config-review.md. Both workers
released and deliveries acknowledged. Full Ruff/format342files, mypy188sources,
package build and863documentation/contract checks passed. No paid calls or ledger
changes. Previous07f6a85 CI35401139089 passed. Full current-suite result follows.

Full local suite completed:2611passed,7skipped,2existingwarnings in211.57s:
`uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`.
Log:/tmp/proofops-raster-config-suite.txt. This validates software regressions,
not whole-report accuracy or an enabled raster dispatch path. Cloud/model trials
for this configuration stage remain not_run.

### 2026-09-19 — scoped raster preparation and legacy downgrade rejection

Added prepare_authorized_raster: reload immutable run/original PDF, compare
run/job/document/manifest and actual execution policy, re-resolve current
runtime/consent/rights, enforce exact selected pages and max_pages, replay native
eligibility, and prepare a deterministic image-only request with job-scoped ID.
Lease, policy and authorization are checked before and after rendering. A failing
regression reproduced consent revocation during rendering being missed, then
passed after the final authority check. No transport or reservation is enabled.

Terra task_0ba27fee40fe / ctx_b4d8238bd382 added one shared checkpoint guard:
any raster_ocr_ field rejects v1-v4 at commit/read; barev5 remains unsupported.
It reported25newtests,65parser/native regressions and47rule tests passing. Review
of the diff confirmed the existing shared boundary protects both paths without
adding a duplicate store guard. Worker released and delivery acknowledged.

Luna task_5cd2d066a9cf / ctx_55f9d02f1f28 reviewed preparation and passed13tests.
Report:/tmp/proofops-raster-preparation-review.md. Accepted its plan-alignment
finding: request now explicitly includes max_pages/max_calls/submitted_pages and
eligible/requested source IDs, all included in request_id derivation. Added a
regression that failed for missing max_pages, then passed with all count/set pins.
Did not add a second pre-render ID: source_ids is a tuple, graph values are frozen,
and final correspondence already pins graph/source/geometry/image bytes. Did not
duplicate rights/consent/runtime profiles: request.input_hash binds the complete
server-side immutable run snapshot, which already freezes all three artifacts;
the review's mutable-snapshot premise does not match LocalSQLiteRunStore's
immutable UPDATE/DELETE triggers. Future readback must resolve and verify this
scoped snapshot, not trust the request envelope in isolation. Worker released.

Focused coordinator preparation/policy/composition suite30passed. Full Ruff and
format345files, mypy189sources, build and863documentation/contract checks passed
before the final additive request fields; final focused checks follow. Prior
9bd4946 CI35402227925 passed. No API calls or budget changes in this stage.

Full suite:2649passed,7skipped,2existingwarnings in205.99s; log
/tmp/proofops-raster-preparation-suite.txt. This run began before the final additive
request fields; those fields passed the30focused tests plus repeated full
Ruff/format and relevant mypy checks. Documentation/contracts863passed again.
The live parser still rejects raster-configured runs until persistent request
accounting and v5 writer/store/readback are integrated. No service-ready claim.

### 2026-09-19 — durable raster dispatch and page-billed accounting

Terra task_be67ac6b6f53 / ctx_efa450339aa3 implemented scoped immutable
raster_request/raster_receipt records over existing job_records. Registration
checks snapshot/request identities and atomically limits registrations across the
run; exact duplicates never redispatch. Original lease owners can retain late
receipts, but no checkpoint is published. Coordinator review requested stored
request-hash recomputation and full message validation, now implemented. After
worker release, coordinator added explicit concurrent duplicate/different-request
races and strict billing-page mode validation shared with offline raster replay.
Four malformed billing cases failed before the shared validator and pass afterward.

Luna task_58627bfa9dee / ctx_5f119b7efc5c fixed request_usage for page-billed
Document Parse receipts without treating absent token measurements as complete.
Mixed token/page/unknown reservations retain costs and pending amounts. Coordinator
added corrupt amount/model/token regressions: list-valued model/provider IDs
initially leaked TypeError, then failed closed as ACCOUNTING_UNAVAILABLE after
shape validation. Both workers released and deliveries acknowledged.

Coordinator dispatch integration uses the real UpstageParseProbe/shared ledger
with an intercepted HTTP method (no paid calls). It proves one call/one reservation,
no resend of ambiguous timeout, late own receipt retained without publication,
wrong-ledger rejection, persisted receipt reuse after store restart and a new
fencing token, and exact native+raster source composition.15store/dispatch tests
passed;28transport/accounting/dispatch tests passed before final billing/race tests.
Ruff import-order failure in test_raster_dispatch was fixed, then full Ruff passed.
Format349files, mypy190sources and package build passed. Full suite pending below.

Read-only replay of the actual saved Doosan raster request confirms4billed pages,
USD0.044, token_usage_complete=false. Evidence:raster-page-usage-replay-20260919.json.
Provider methods forbidden during replay; zero API calls/ledger writes. Shared
ledger remains1752calls,USD9.2214240400 committed/reserved,7unsettled. Priorb435b03
CI35403078623 passed. The live parser is still disabled for raster mode until
coordinated v5 checkpoint publication/readback and coverage are implemented.

Full application regression suite completed:2672passed,7skipped,2existingwarnings
in199.96s (unit/contracts/acceptance/integration/security/staging E2E gate), log
/tmp/proofops-raster-dispatch-suite.txt.864documentation/contract checks passed.
The worktree's only change during this run was test import ordering; runtime code
was stable. No workers await release (19released;3historical retained records).
