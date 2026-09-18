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
