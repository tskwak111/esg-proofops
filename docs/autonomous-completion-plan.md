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
