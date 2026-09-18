# Live tagging contract audit — bounded Developer A read-only — 2026-09-18

Scope: read-only audit from current real Upstage extraction + source-verified native checkpoint to a real Upstage tagging worker. No code/test edits, no paid/network API calls, no secrets, no commits. Baseline is `feature/developer-a-service-validation` at 2208 passed 7 skipped; shared paid-product-model ledger `.local/upstage/budget.sqlite3` now at 1374 rows / USD 7.9351222000 committed-or-reserved (6 unsettled) / authorized ceiling USD 20.00 (base 10 + one 10.00 extension at 2026-09-18T12:57:43Z). Native paragraph attestation v4 and KB native pilot (`.local/developer-a-service-kb-native`, 29 verified / 109 unresolved, 2 verified claims / 5 unverified, tag blocked) are prior native integration, not proposed here. This file is the only artifact written.

## 1. Exact blockers (file:function)

**B1 — LocalTagRunner synthetic gate.** `apps/worker/src/proofops_worker/tag_runner.py:62-63 LocalTagRunner.__init__` rejects `transport.synthetic is not True`; `:78-83 composition tag runner` only supplies `SyntheticTaggingTransport()` when `LOCAL_TAGGING_MODE==local_synthetic` else `None`. `apps/worker/src/proofops_worker/composition.py:34-35 build_composition` rejects any non-empty `LOCAL_TAGGING_MODE` not equal to `local_synthetic`. Result: `UpstageTaggingTransport` at `apps/agent/src/proofops_agent/upstage_tagging.py:29-48` (real, `synthetic=False`, model `MODEL_PROFILE="upstage-compact-ids-frozen-unicode-v1"`) can never be injected; `:99-103 _execute` always yields `TAGGING_RUNTIME_REQUIRED`.

**B2 — TaggingSettings/run-store pin to synthetic.** `packages/proofops/application/tagging/service.py:60 TaggingSettings.__post_init__` requires `binding.role=="tagger"` and explicit `synthetic` bool; `packages/proofops/adapters/local/tag_store.py:28-42 tagging_settings()` requires `tagging_mode=="local_synthetic"`, `binding.synthetic==True`, and `binding.binding_id==runtime.runtime_binding_id` and `max_tokens<=runtime.max_output_tokens`; `packages/proofops/application/runs.py:190-202 RunService.create` rejects any `tagging_settings` where `synthetic is not True` or mode not `local_synthetic`; `apps/api/src/proofops_api/local_runtime.py:131-164 _tagging()` rejects `binding.synthetic is not True` or `role!="tagger"` or `temperature!=0` with `LOCAL_RUNTIME_CONFIG_INVALID`. Real transport needs `synthetic=False` and a separate mode value that does not exist.

**B3 — Run creation / extraction-vs-tagging coupling.** `packages/proofops/adapters/local/run_store.py:105-112 create()` assumes extraction-only when `extraction_mode=="upstage_probe"` → `snapshot rulepack_use=="extraction_reference_only"` and forbids any `tagging_settings`; `packages/proofops/application/runs.py:174-188` similarly gates `upstage_probe` to `scope==declared_subset`, `tagging_settings is None`, and `extraction_limits {max_calls,max_output_tokens}`. `apps/api/src/proofops_api/local_runtime.py:194-253 load_local_runtime` forbids `tagging_settings` without `extraction_mode`, forbids `extraction_limits` without `upstage_probe`, and in that branch forbids any `tagging_mode`. There is no compatible path for extraction+tagging on the same run, or extraction `upstage_probe` + tagging `local_synthetic`, or both `upstage_probe`.

**B4 — Preflight role restriction to extractor-only for the Upstage local path.** `packages/proofops/application/preflight.py:352-360 check_local_upstage_binding` validates `binding.role=="extractor"` and `model_id in ("solar-pro3","solar-pro4")` and `model_sha256==canonical_hash({model,provider,transport})`. `packages/proofops/application/runs.py:148-155 create()` passes only `probe_model_sha256` from the frozen `ExtractionProfile` into that check; no tagger hash path exists. A real tagger binding (role `tagger`, `MODEL_PROFILE` hash, endpoint `https://api.upstage.ai/v1/chat/completions`) has no preflight gate.

**B5 — Missing `count_input_tokens` wiring (real input-token reservation).** `packages/proofops/application/tagging/service.py:181-182 tag_replicates` requires `count_input_tokens: Callable[[dict],int]` for any non-synthetic binding (`TAGGING_INPUT_COUNTER_REQUIRED`); `:400-412` reserves via `reserve_budget(... input_tokens=count(...))`. `apps/agent/src/proofops_agent/upstage_tagging.py:58-65 count_input_tokens(request, counter)` supplies validated wire system/user builder, but `LocalTagRunner._execute:170-186` always injects `token_counter=self.transport.token_counter` (the legacy synthetic path) and never supplies `count_input_tokens`; the real adapter’s method needs a two-arg counter `(system,user)->int` and distinct from the single-string fallback. Without composition wiring, reservation fails before spend with `TAGGING_INPUT_COUNTER_REQUIRED` or later `TAGGING_INPUT_COUNT_INVALID`.

**B6 — Preliminary classification supplier absent.** `apps/worker/src/proofops_worker/tag_runner.py:104-105,119 _execute` requires `self.preliminary is not None` else `PRELIMINARY_TAGS_REQUIRED`; then calls `preliminary(claim,graph) -> (TrackCandidate, ClaimContext, relation_tags)` validated by `packages/proofops/application/tagging/tracks.py:validate_track_candidates`. No real supplier is wired; both `composition.py:80 tag` and `RunService` leave it `None`. Tagger cannot freeze classification for wire schema pinning (`upstage_tagging.py:86-98` requires frozen `track/safe_harbor_category`).

**B7 — Evidence / source-scope / binding verification still gated.** `packages/proofops/application/tagging/service.py:191-274` and `packages/proofops/application/evidence/retrieval.py:286-384 retrieve_evidence` enforce `claim.source_quality=="verified"`, verified-span containment, `unassigned_note_ids/unresolved_source_issue_ids` blocks, `open source quality→blocked_evidence`, and `P4/P6/empty-refs/absent/not_applicable → unknown`. The native v4 receipt (`packages/proofops/adapters/local/source_verification.py:attest_native_sources`, `run_artifacts.py:105-129,193-258`) verifies only paragraph native+rendered text within 0.001pt clip tolerance, not tables/footnote binding or relationship validation. KB native pilot verified 29/138 source blocks; all non-paragraphs remain `relationship_validation_required` → unassigned remains `TAGGING blocked`.

**B8 — Budget dual-authority tension (UpstageProbe reservation vs UsageRepository reservation).** `packages/proofops/adapters/local/upstage.py:46-53 POLICY {reservation_usd:"1.00", limit_usd:"10.00"}` + `probe_extensions` additive cap, plus per-request `canonical_hash(request_id).json` archiving under `.responses`. Tagging also reserves via `packages/proofops/adapters/aws/usage.py:LocalSQLiteUsageStore` → `BudgetLimits/Roles` and `PricingSnapshot`. `packages/proofops/application/runs.py:256-301 cost()` already distinguishes extraction/tagging cost summaries (`request_usage()` over ledger IDs for extractor; `cost_summary` over `cost_data` for tagger). A real tagger must not invent a third USD ledger nor treat synthetic UTF-8 bytes as cost.

## 2. Technical vs truly requires new human domain input

**Purely technical (no new domain approval; code/config/preflight composition change):** B1, B3-wire portion, B4-role extension, B5 counter wiring, B6 supplier wiring, B8 ledger disambiguation. Fixes are mechanical: new mode value, explicit real-provider validation branch, request counting adapter, preliminary supplier injection, and keeping the existing shared USD ledger as sole monetary authority.

**Technical but measured by native verification quality (human review of coverage, not of domain labels):** B7 source-scope. No new legal classification needed, but operator must decide which PDFs/regions to run `verify-paragraphs + native OCR` on, and whether to expand verification beyond paragraphs. Grades still come from `packages/proofops/domain/rules/engine.py:evaluate` only; LLM never grades.

**Truly requires new human domain / rights input (must not be invented — domain gaps remain domain-gated):** Any activation that changes legal-effect presentation:
- `contracts/domain_gaps.json:GAP-001..010` — e.g. GAP-001 safe-harbor → E/label mapping not approved (`safe_harbor.legal_effect=="not_determined"`, `mapping_status=="unresolved"`), GAP-004 `explicit_link`/global element scope, GAP-005 PERF/IMPL sublabel, GAP-008/009 clause numbers / regulatory effect. These are `blocked_rule_gap / decision_status != decided` by design; tagging must not invent grades or “safe” labels.
- Rights/license gate per PDF after parsing: `registry` `rights_profile_id` ∈ `consent.allowed_document_rights`, and `consent.allowed_source_sha256` scope for the real probe (`preflight.check_local_upstage_binding document_scope check`). Requires tenant owner to supply consent/rights/region approval; not a code inference.
- Price recheck is human-date-gated but already satisfied: `upstage.py:304-305 PRICE_RECHECK_REQUIRED` expires 2026-09-25 00:00 UTC; `evidence/upstage-price-recheck-20260918.json` verified Pro3 $0.15/$0.60 and Pro4 $0.30/$1.20 with VAT 1.10 on 2026-09-18, so current ledger pricing remains authorized — no new price invention.

Do NOT resolve blockers by: `synthetic=True` on the real transport (`docs/28` forbids lying provenance), deleting `SOURCE_VALIDATION_REQUIRED`/`EVIDENCE_PACKET_BLOCKED`/`absent→unknown`/`P4/P6→unknown` guards, trusting `unverified` source text, or inventing safe-harbor thresholds, grade criteria, clause numbers, or pricing.

## 3. Coordinator review: runtime contract is still a proposal

The worker sketch was not accepted as a compatible contract: one `runtime` field
cannot simultaneously represent the existing extractor-only approval and an
independently authorized tagger. Before implementation, define a new snapshot
version with explicit extractor/tagger bindings and preflight for both, retain
legacy extractor-only and synthetic snapshots, and document rollback. A Python
callable is runtime code and must not be serialized into a snapshot; pin its
implementation/version and configuration instead. Cross-run tagging is not an
existing feature and is not assumed by this audit.

Do not silently accept `upstage_probe` while injecting no transport. Keep the
current explicit unsupported-mode error until its complete runtime branch exists.
No grade or source guard should be weakened to make the branch reachable.

## 4. Provider token counting limitations & lawfulness of existing UTF-8 accounting

**What the ledger actually bills.** `adapters/local/upstage.py:293-397 UpstageProbe.complete` settles with VAT-multiplied cost from `application/budget.usage_cost` using `provider usage {prompt_tokens, completion_tokens}` + fixed `PRICE/PRICE_PRO4` snapshots (`upstage-solar-pro3-2026-09-09` $0.15/$0.60, `upstage-solar-pro4-2026-09-12` $0.30/$1.20) and archives decoded HTTP-200 JSON under `.responses/<hash(request_id)>.json`. Reservation is always USD 1.00 pre-call regardless of size; unknown/invalid receipts retain the reservation.

**Why pre-call estimation is needed but non-trivial.** Tagging reserves via `application/budget.reserve_budget` → `adapters/aws/usage.py:LocalSQLiteUsageStore` before dispatch. `service.py:181 tag_replicates` now mandates `count_input_tokens(request:dict)->int` for any non-synthetic binding; `upstage_tagging.py:58-141 _wire_request` exposes the exact wire `system,user` (with compact evidence IDs `e0…`, `MODEL_PROFILE`-pinned schema, literal Unicode) so counting matches billed input. The wire builder and the counter must be the same revision (`transport_version "compact-evidence-ids-v1"`; `local-upstage-tagging-contract.md`).

**Limitation: no validated local tokenizer equals billed input today.** `evidence/tagging-wire-accounting-verification.md:38-43` checked `upstage/solar-pro3-tokenizer` at `c41b71f`; it has no `chat_template` and disables BOS/EOS — it does not reproduce Upstage chat framing. `upstage.py:359-365` validates `provider_request_id uniqueness` but does not derive input tokens from output. Consequently a local char/BPE estimate will differ from billed `prompt_tokens` (especially for Korean literal Unicode where byte length ≫ token count and where system prompt + schema + evidence catalog are part of billed input).

**Can existing UTF-8 accounting be reused lawfully?** No for the real transport. `apps/agent/src/proofops_agent/synthetic_tagging.py:18-21 SyntheticTaggingTransport.token_counter` returns `len(text.encode("utf-8"))`; `service.py:405 token_counter(rendered_system+user_json)` concatenates messages and ignores framing. The contract at `local-upstage-tagging-contract.md:49-53`, `application/budget.py:1-3`, and `service.py:178-182` states: synthetic byte counts are `synthetic-only` legacy fallback; non-synthetic tagger must supply a validated provider-specific counter accounting for chat framing (`counter(system,user)`) or use the post-call provider usage as settlement ground truth and keep the pre-call gate conservative. Reusing UTF-8 bytes as `input_tokens` for a `synthetic=False` binding would under- or over-reserve tokens, bypass `BudgetLimits` branch `max_input_tokens` checks, and misreport `cost_summary` (`pricing_snapshot_id null → unknown_cost`).

**What remains to satisfy technically.** Install a validated `counter: (system,user)->int` supplied by the caller (composition) that mirrors Upstage chat framing for the bound model (`solar-pro3` vs `solar-pro4`) and is covered by `TAGGING_INPUT_COUNT_INVALID` validation (`service.py:407-411` → `invalid_request`). Cache recovery (`cache.get_raw`) skips counting entirely (`tagging-wire-accounting-verification.md:15-16`). Until an admissible counter/reservation contract is pinned, keep real tagging blocked. `pricing=None` does not remove `TAGGING_INPUT_COUNTER_REQUIRED`.

## 5. Coordinator review: next implementation boundaries

1. Define and test independently pinned extractor/tagger bindings, authorization,
   token accounting, shared monetary ledger and immutable checkpoint compatibility.
2. Implement an auditable preliminary classifier that extracts track and literal
   dimension references. Unsupported/ambiguous output must block tagging. Do not
   hardcode `management` or a safe-harbor category for the KB pilot or another company.
3. Wire the real transport only after both contracts exist. Test expiry, foreign
   tenant/source, cancellation, duplicate attempts and provider failure before
   another bounded live probe. Preserve the domain rulepack approval gate.

The worker suggestion to hardcode a pilot track and to bypass a missing input
counter by setting `pricing=None` is rejected. Unknown pricing does not waive
input-token limits. The official tokenizer was independently located by the
coordinator at https://huggingface.co/upstage/solar-pro3-tokenizer; framing parity
and deployment license acceptance are not established by merely finding it.
No live tagging call, token-counter implementation or runtime-schema change was
made in this audit.

## Appendix — evidence anchors

Extraction real path: `apps/agent/src/proofops_agent/upstage_extraction.py:89-250 UpstageClaimExtractor`, `adapters/local/upstage.py:137-257 authorize_additional_budget/_reserve/_settle`, `worker/extract_runner.py:39-125 LocalExtractRunner`. Native checkpoint: `adapters/local/source_verification.py:attest_native_sources`, `adapters/local/run_artifacts.py:105-258`. Tagging synthetic-vs-real boundary: `adapters/local/models.py:24-57 SyntheticTagger/BedrockTagger`, `apps/agent/src/proofops_agent/tagger.py:18-68 BedrockMessagesTagger`, `domain/values.py:49-51 _FORBIDDEN_LLM_FIELDS`. Preflight/budget: `application/preflight.py:293-395`, `application/runs.py:256-301`, `adapters/cache/aws.py:155-254 ImmutableResponseCache`. Current ledger invariant: base `POLICY limit_usd 10.00` + one authorized extension 10.00 = 20.00 ceiling; 6 unsettled USD1 reservations retained.

## Independent tokenizer recheck (coordinator)

On 2026-09-18 the official Hugging Face model metadata and raw tokenizer config
were fetched with TLS verification enabled. Revision remains
`c41b71f0519c580610cb0fd2af4ed2b23cad544f`; it is not gated, license metadata is
`upstage-solar-license`, `chat_template` is absent, and BOS/EOS auto-add are false.
Source: [Upstage Solar Pro3 tokenizer](https://huggingface.co/upstage/solar-pro3-tokenizer).
This confirms availability, not API chat-framing parity. No dependency was installed
and no account/credit purchase or tagging model call was performed for this check.
