# Service readiness implementation plan

Goal: make the existing E-claim evidence-review workflow usable with real PDFs
and measured model output, without treating unverified extraction as substantiation.
User authorized autonomous implementation, evaluation and external API comparison
on 2026-09-12. The cumulative test budget remains USD 10; domain gaps stay gated.
Spec: 00_MASTER_SPEC.md, 27_PARSING_AND_PROVENANCE.md,
28_RULE_ENGINE_CONTRACT.md, 31_DOMAIN_IMPLEMENTATION_GAPS.md and original v2.

## Working approach

Keep source provenance, numeric checks and pure Python rules. Compare existing
local parsing against an external parser on identical selected pages before
changing parser defaults. Integrate real extraction with the existing review UI;
unknown source quality and unresolved semantics must be visible, never synthetic
success. Reuse existing storage and budget ledger, avoid new services/dependencies.
Public deployment and approval-dependent domain decisions remain separate gates.

## Execution waves

- [ ] Parser comparison: add bounded Upstage Document Parse transport beside the
  existing text probe. Reserve each call in the same SQLite ledger, no retries,
  fail closed on incomplete usage/receipt, preserve raw responses and page maps.
  Verify duplicate IDs, budget exhaustion, bad page count and malformed receipts
  with failing-first tests. Use at most ten pages per request and an initial
  3-report / 3-page-per-report sample; compare standard and enhanced modes within
  the remaining budget. Record time, price, table value-year-unit and source
  location findings. Development review is not human-approved benchmark gold.
- [x] Real extraction integration: trace synthetic composition gates, reuse the
  structured extractor and real transport, add explicit opt-in configuration,
  immutable receipts and source-bound candidate review. Verify upload-to-review
  with a real report, plus model errors, budget stops and source-quality blocks.
- [ ] Evidence connection: evaluate candidate retrieval and structured table/claim
  dimensions across multiple reports; choose local/API stages using observed
  omissions and attribution errors. Preserve source-quality gates and null grades
  until their inputs are accepted. No arbitrary domain thresholds or unit repairs.
- [ ] Product acceptance: run lint/type/unit/integration/contract/build/security
  and browser workflows, including failure/retry/review conflicts and exported
  source links. Keep a release checklist separating observed results, unmeasured
  metrics and approval/deployment blockers. Do not claim production readiness
  from passing code tests or a small development sample.

Coordinator owns shared integration, Git and evidence. Orca workers have explicit
file ownership. No push, deployment or budget increase is implied by this plan.

## Current official parser inputs

Checked 2026-09-12: https://www.upstage.ai/pricing/api lists Document Parse
standard USD 0.01/page, enhanced USD 0.03/page, excluding 10% VAT. Nine pages in
both modes would reserve an estimated USD 0.396 in settled usage. Ambiguous or
failed calls retain the existing USD 1 per-call reservation.
https://console.upstage.ai/api/parse/document-parsing specifies multipart POST
to /v1/document-digitization, usage.pages and per-mode page lists, normalized
element coordinates and mode selection. Enhanced is supported from
document-parse-260128. Store actual returned model version; never infer quality
approval from provider branding or agreement with another extraction engine.

Compatibility: evaluation adapter additions do not alter API/DB schema or prior
receipts. Rollback disables the new opt-in transport and preserves its artifacts.
Any later runtime contract/migration change must be recorded before implementation.

## Checkpoint 2026-09-12

Parser comparison wave implemented and exercised (five successful calls and one
429 retained reservation); findings are in `evidence/parser-extraction-comparison.md`.
Real extractor adapter is implemented with source-exact validation and shared
budget. Fixed Unicode-escaped model input; same-source development probes moved
from 0/3 valid responses to 3/3. This completes the adapter slice, not the full
API/worker/UI integration wave. Model-output errors preserve unknown; budget and
rate-limit conditions stop instead of iterating through remaining blocks.

Next executable slice: define explicit local real-extraction runtime/usage contract
and bounded block scheduling, then wire candidate review without synthetic tags.
Do not mount an Upstage transport under a synthetic consent/runtime binding.
Remaining API/DB compatibility, processing bindings and browser gates must be
resolved before claiming upload-to-real-review service readiness. Public release
is blocked, not approved by these development measurements.

## Local integration checkpoint (2026-09-12)

See `evidence/local-upstage-service-pilot.md`: actual upload/extraction/browser path
and USD10 accounting verified with 24 calls. Matched-packet prompt improvement is
development evidence only. Next: stable bounded paragraph selection, independent
extraction validation, then E + ESG DATA + APPENDIX evidence integration. Existing
UUID-based discovery order must not be mistaken for a repeatable sampling strategy.

## Cross-report checkpoint (2026-09-12)

Stable bounded paragraph selection and section navigation repairs are implemented.
Five additional companies were exercised: four original parses succeeded; one
original with automatic Print was rejected. Same-source prompt and standard/enhanced
API comparisons are archived in `evidence/cross-report-service-evaluation.md`.
The experimental prompt was not promoted because results were mixed. Next execute
existing parent-context/sentence pilots against frozen multi-company inputs, then
source-reviewed evidence attribution. Independent gold, numeric table validation
and release acceptance remain open; do not treat page coverage as accuracy.

## Model comparison contract — 2026-09-13 KST

The context/selection experiments on five frozen company samples did not justify
changing runtime defaults. Compare Solar Pro 4 using the same Upstage endpoint,
key and **existing** cumulative USD10 ledger. Official API example specifies
`solar-pro4` at `https://api.upstage.ai/v1`, with `reasoning_effort=medium`.
The provider's read-only `/v1/models` response additionally confirms exact version
`solar-pro4-260806` (archived `.local/context-loop/provider-models.json`).
Sources checked 2026-09-12 UTC: https://www.upstage.ai/blog/en/solar-pro-4 and
https://www.upstage.ai/pricing/api. Reserve undiscounted USD0.30 input / USD1.20
output per million tokens plus10%VAT; do not assume promotional eligibility.

Compatibility: default Pro3 behavior/price and stored budget policy remain unchanged;
explicit alternative calls record their own model/price snapshot in existing receipts.
No database migration, ledger reset, API/DTO change, runtime consent substitution or
source-quality promotion. The Pro3 frozen extractor rejects an explicitly Pro4
transport until a separately pinned runtime profile is implemented and tested.
Rollback disables alternative probes and preserves every paid receipt/reservation.

Pro4 canary correction: medium reasoning exhausted a 4096-token output budget with
no final answer and another request timed out. Both reservations remain unknown.
The official chat guide (https://console.upstage.ai/docs/capabilities/generate/chat)
states Pro4 reasoning is off by default. The bounded extraction probe now omits
reasoning_effort; compare at the same 1024-token cap as the Pro3 baseline. This is a
new explicit configuration experiment, never an automatic retry of the failed calls.

Source-fidelity correction (2026-09-13 KST): exact substrings can still remove part
of a word (observed `지분투자` → `투자`). New claim validation rejects boundaries
inside contiguous alphanumeric tokens; it never auto-expands or rewrites the quote.
The Upstage rule descriptor changes for new extraction profiles. Existing revisions,
receipts and recorded experiment results remain immutable. No API/DB shape change;
rollback restores the prior validator/profile code without rewriting prior results.

## Context/model loop checkpoint (2026-09-13 KST)

Five-company context and model experiments plus15 new E pages completed. Pro4
can now run only under an explicit matching local profile; defaults stayPro3.
Real Kia/NAVER upload/extract/API trials passed, but still produced untagged
candidates and one unstable numeric-table selection. See
`evidence/context-loop-verification.md`; automatic service readiness is not met.
Next address table reconstruction/evidence separation before broader live tagging.

## External table candidate contract (2026-09-13 KST)

Three original-page standard/enhanced comparisons recovered table structure that
local parsing split into headers and paragraphs. Implemented evaluation-only HTML
cell parsing and a converter into existing CandidateBatch/NativeSource types.
All table elements are eligible; never use company/metric-name whitelists. Preserve
merged row/column spans and exact decoded cell text; no semantic header approval.
Rebuild the requested PDF subset from original bytes and physical-page mapping,
then verify its request hash and the archived raw-response hash before conversion.
Only unrotated, full-origin MediaBox=CropBox geometry is supported initially; reject
other geometry instead of approximating. Table rectangles use actual provider
normalized coordinates. Cells have no bbox because the provider supplies none.
Use a fresh parse manifest; do not mutate stored local graphs or fuse mismatched
manifests. Standard/enhanced share one parser family, not independent votes.
No network, new dependency, API/DB shape change, runtime promotion, source-quality
approval or numeric acceptance is granted by conversion. Rollback removes this
opt-in evaluator and preserves every source/response artifact.

Six final-code offline replays retained five unique tables/81 cells, with no cell
locations or numeric observations. See `evidence/table-recovery-verification.md`.

## Sentence/table context loop — 2026-09-13 KST

New Upstage profiles opt into paired-quotation truncation checks; legacy snapshot
replay retains its old validator behavior. This is a source-fragment guard, not
assertion/grammar approval. Table evaluator versions5–8 preserve merged spans,
own-row identity, stable header aliases, source row order and target-only prompts.
No API/DB schema change or source-quality promotion. Rollback disables the new
extractor profile/evaluator and preserves old snapshots and paid receipts.
Four real five-table configurations passed3/5,5/5,3/5,5/5 structural checks;
semantic quality is still unmeasured. See `evidence/service-loop-verification.md`.
Actual Upstage element-tagging service composition remains engineering work; do
not describe its absence as solely a human/domain-approval blocker.

## Semantic evaluation checkpoint — 2026-09-13 KST

Thirty real paragraph calls across five development companies and a Kiro
source-only review reproduced whole-response loss from one rewritten quote.
New profiles retain exact siblings; rejected and uncovered text stay unknown.
Offline replay changed only one paragraph; this is not independent accuracy
evidence. Table-role vocabulary lacks numeric/header roles and remains a
model-proposed diagnostic, with source coordinates unverified. Prioritize held-out
company/source review, quantitative/header binding, mixed-cell context and the
actual tagger composition before service claims. See
`evidence/semantic-review-verification.md`.
