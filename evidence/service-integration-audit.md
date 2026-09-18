# Service integration audit — real PDF → reviewable extracted-claim run

Scope: read-only repo audit. Only this file written. No code, commit, credential, API call, or deployment changed.
Date (UTC): 2026-09-12. Coordinator owns integration/fixes under user authorization.

## 1. Two paths that exist today (do not confuse them)

### A. Real-model path (evaluation-only, NOT wired to API/UI/worker)

- `evaluation/upstage_live_probe.py:52-69 load_graph` — loads a real document graph (the separate `run` function selects a hard-coded paragraph) via `OpenDataLoaderParser.load_verified` from an existing manifest. Not an upload API.
- `evaluation/upstage_live_probe.py:69-145 run` — builds `UpstageProbe(key, .local/upstage/budget.sqlite3)`, calls `client.complete(SYSTEM, packet_json, request_id, max_tokens=4096)`, writes `.local/upstage/<request_id>/result.json` with `synthetic:false, decision:None, validation_status: passed|failed`.
- `evaluation/upstage_live_probe.py:28-50 locate_quotes` — resolves exact unique quotes, then `validate_extraction_response` (from `packages/proofops/application/claims.py:81`). Grade/label output rejected by shape.
- `packages/proofops/adapters/local/upstage.py:41-200 UpstageProbe` — `solar-pro3`, fixed host `api.upstage.ai`, no redirects/tools/uploads, 16 KiB request cap, per-call USD 1 reservation against USD 10 ceiling (`POLICY`), price expiry 2026-09-16 (`PRICE_RECHECK_REQUIRED`). Ledger `.local/upstage/budget.sqlite3` (600).
- `evaluation/section_pipeline.py:45-63 plan_for_graph`, `:140-225 SectionSearch` — candidate-only section scope + Korean-bigram BM25 bounded search over the same immutable graph; implements `EvidenceSearchPort` shape but is eval-only, never called by worker/API. Status stays `candidate_only` / `binding_status=undetermined`.
- Proven by `evidence/upstage-live-verification.md`: 5 calls, 3 settled USD 0.0005586900, ledger committed USD 2.0005586900, one-paragraph literal match only; no atomicity/recall/grade/source-quality approval.

### B. Local app composition (upload → parse → extract → tag → review; synthetic-only)

Upload (real PDF bytes, synthetic storage):

- `apps/api/src/proofops_api/routers/documents.py:219-442` → `packages/proofops/application/uploads.py:275-653 UploadService`: `create_document / initiate_upload / receive_content (application/pdf only, sha256+size check) / complete_upload → verify_and_promote → immutable version ready`.
- Mount guard `build_documents_router(...):162-164` fails closed unless `app_env==local and model_adapter==synthetic and service.local_synthetic`.

Run creation (frozen inputs, never invokes models):

- `apps/api/src/proofops_api/routers/runs.py:172-185 create_run` → `packages/proofops/application/runs.py:87-192 RunService.create`. Requires `parser_profile + parser_profile_hash + budget_limits`, runtime/consent/rights registry resolution, preflight + `verify_supply_chain`.
- Mount guard `build_runs_router:110-111` + `RunService.__init__:59-60` reject non-`local-synthetic`.
- `apps/api/src/proofops_api/local_runtime.py:184-239 load_local_runtime` is the config gate: `LOCAL_EXTRACTION_MODE/LOCAL_TAGGING_MODE ∈ {"", local_synthetic}`; `_extraction` demands `synthetic is True`; `_tagging` demands `binding.synthetic is True, role==tagger, temperature==0`.

Worker stages (fenced, one delivery each):

- `apps/worker/src/proofops_worker/composition.py:24-78 build_composition(stage)` — `parse|extract|tag`; extract raises `EXPLICIT_LOCAL_SYNTHETIC_EXTRACTION_REQUIRED` unless `LOCAL_EXTRACTION_MODE=local_synthetic`; tag passes `SyntheticTaggingTransport()` only if `LOCAL_TAGGING_MODE=local_synthetic` else `None`; extract always `SyntheticClaimExtractor()`.
- `apps/worker/src/proofops_worker/local_runner.py:60-170 LocalParserRunner.run_once` — `consume_job` parse → `OpenDataLoaderParser.parse` → `load_verified` → checkpoint `local_parser_checkpoint_v1`, enqueues `extract` (`uuid5(job_id,"extract")`).
- `apps/worker/src/proofops_worker/extract_runner.py:39-125 LocalExtractRunner.run_once` — `discover_atomic_claims(graph, claim_scope, extractor=FencedExtractor(SyntheticClaimExtractor))` → checkpoint `local_extract_checkpoint_v1`, enqueues `tag`.
- `apps/worker/src/proofops_worker/tag_runner.py:78-250 _execute`, `:252-325 run_once` — per-claim gate block (see §2), else `retrieve_evidence` (with `_LocalClaimSearch` bounded synthetic) → `freeze_track_packet` → `tag_replicates` (3 replicas) → `form_consensus` → `evaluate` (pure-Python engine) → `ReviewService.publish_transaction`.
- `apps/worker/src/proofops_worker/consumer.py:42-89 consume_job` — lease/fence/cancel semantics; usage retained on `StageFailure`.

Reviewable reads (existing UI/API surface):

- `apps/api/src/proofops_api/routers/claims.py:128-206 claims_list` (via `LocalClaimStore.page`), `:208-252 claim_get` (requires `tags + current_tag`, else `TAGGING_NOT_PUBLISHED`).
- `apps/api/src/proofops_api/routers/sources.py` (`source_get/source_view/quality_get` from `load_run_graph`), `routers/reviews.py` (`reviews_list/review_resolve`, reviewer role + CSRF + If-Match).
- Web: `apps/web/src/features/runs/RunForm.tsx`, `RunProgress.tsx`, `CoveragePanel.tsx`, `features/claims/ClaimWorkspace.tsx`, `features/reviews/ReviewWorkspace.tsx`, `components/SourceViewer.tsx`.

## 2. Current synthetic gates (exact locations — keep until real bindings approved)

1. `packages/proofops/composition.py:59-102` — only `synthetic|bedrock`; non-local fails closed; `BedrockTagger.tag` always raises (`adapters/local/models.py:53-57`).
2. `apps/api/src/proofops_api/local_runtime.py:138-145 _tagging`, `:171-181 _extraction` — non-synthetic binding/profile → `LOCAL_RUNTIME_CONFIG_INVALID`.
3. `packages/proofops/application/runs.py:141-160` — non-synthetic extraction/tagging settings → `CONFIG_GATE_BLOCKED`.
4. `apps/worker/src/proofops_worker/composition.py:29-30, 62-67` — extract hard-requires `local_synthetic`; tag transport `None` without the env flag.
5. `apps/agent/src/proofops_agent/extraction.py:36-42 SyntheticClaimExtractor` (lexical heuristic) and `apps/agent/src/proofops_agent/synthetic_tagging.py:7-60 SyntheticTaggingTransport` (all elements `unknown`, `synthetic_unresolved`) — the only wired extractor/transport.
6. `apps/worker/src/proofops_worker/tag_runner.py:99-107` — per-claim block reasons that MUST stay: `SOURCE_VALIDATION_REQUIRED` (quality != `verified`), `TAGGING_RUNTIME_REQUIRED` (settings/transport None), `PRELIMINARY_TAGS_REQUIRED` (preliminary None), plus `EVIDENCE_PACKET_BLOCKED`.
7. `packages/proofops/application/tagging/service.py:186-267` — tag guards: `claim.source_quality != verified` → reject; packet identity/candidate/content_trust checks; verified-span containment; open-issue block; `absent/not_applicable/P4/P6/empty-refs → unknown`.
8. `packages/proofops/application/claims.py:205-226 discover_atomic_claims` — `conflicted/unreadable → conflict/unreadable`, empty → `unknown`, failures → `unknown`; never quota-capped; offsets NFC end-exclusive.
9. Null-grade rule: Master §1 — gaps return `decision_status=blocked_rule_gap, evidence_grade=null, label=null`; `Claim.to_summary` leaves `track/decision` unset (`claims.py:141-151`).

## 3. Smallest safe path: uploaded real PDF → reviewable real extracted-claim run

Goal is deliberately NARROW: real extraction receipts + claim list reviewable in existing API/UI, with grades still null and tagging still blocked. Full 3-replica real tagging + auto-decisions are explicitly out of this slice.

Proposed bounded order (each step: failing test → minimal impl → real verification):

1. **Real extraction adapter behind an explicit port** — new `UpstageClaimExtractor(profile synthetic=False)` implementing `ClaimExtractorPort` (`claims.py:64-68`) by wrapping `UpstageProbe.complete` + `locate_quotes`-style strict resolution + `validate_extraction_response`. Tests: ambiguous/absent/overlap/grade-output rejected; receipt (`packet_sha256/response_sha256/profile/status`) preserved; raw model content saved before extraction validation (the existing probe does not archive invalid native provider receipts). Unblocks: extract stage can run on real PDFs without touching tag guards.
2. **Worker/API plumbing for extraction-only real mode** — add `LOCAL_EXTRACTION_MODE=upstage_probe` (or similar) branch in `worker/composition.py:29-30,68-77` + `api/local_runtime.py:184-239` (`_extraction` allow `synthetic=False` with pinned `model_sha256/prompt_sha256`), and relax `runs.py:141-146` for extraction-only while keeping tagging gates closed. Tests: run create succeeds with real extraction profile; tag stage still returns `blocked/TAGGING_RUNTIME_REQUIRED`; composition rejects unknown modes. No change to `composition.py` model_adapter until preflight/binding approval exists.
3. **Per-block extraction receipts → existing claim reads** — reuse `LocalExtractRunner` + `LocalClaimStore` (`claim_store.py:48-99` replay validation, `snapshot_pins`, `discovery_coverage`) so `GET /v1/runs/{id}/claims` lists real claims with `decision:null, track:null`. Tests: extract checkpoint pins/coverage assertions (`validate_extract_commit:233-309`) pass with real receipts; replay mismatch → `CLAIM_SNAPSHOT_REPLAY_MISMATCH`.
4. **Review queue surfaces extraction unknowns** — real claims with `source_quality != verified` or missing preliminary stay `blocked/needs_review` via `tag_runner.py:99-117`; `GET reviews` + `ClaimWorkspace/ReviewWorkspace` show them; human edits tagging only (If-Match), never labels directly. Tests: unverified claim → `SOURCE_VALIDATION_REQUIRED`; resolve path unchanged.

Explicitly NOT in this slice: real `tag_replicates.invoke` transport, `preliminary` classifier, `EvidenceSearchPort` production index, `RulePackSnapshot` auto-`decided` changes, S3/DynamoDB/SQS/Bedrock wiring, ad-mode/multi-year comparison.

## 4. Concrete missing interfaces/callers (the integration gap list)

- `ClaimExtractorPort` real impl: only `SyntheticClaimExtractor` / caller-owned `StructuredClaimExtractor` exist; nothing calls `UpstageProbe` as an extractor (signature mismatch: `complete(system,user_json,request_id)` vs `extract(packet)->dict`).
- Tag-side real transport: `tag_replicates(..., invoke)->RawTagResponse` has only `SyntheticTaggingTransport`; no Upstage tagger implementing budget/cache/identity envelope (`service.py:364-427`).
- Composition: `packages/proofops/composition.py` has no `upstage` adapter; `ModelBinding(role=tagger/extractor, synthetic=False)` issuance + approval path missing (TASK-029 preflight territory).
- `LocalTagRunner(preliminary=None)` default: no caller supplies source-backed preliminary track/context (`tagging/tracks.py` validation exists, supplier missing).
- Retrieval: production `EvidenceSearchPort` impl missing; `_LocalClaimSearch` (bounded, synthetic) and eval `SectionSearch` are the only impls.
- Budget: probe `POLICY` ledger (USD 10, USD 1 reservation) is disconnected from `RunService BudgetLimits / UsageRepository / PricingSnapshot` used by `tag_replicates`.
- Extraction calls once per block; three replicas are a tagging requirement, not an established extraction gap. Real block-level call volume and usage accounting still need integration.
- UI: no extraction-status/claim-quote review affordance difference between synthetic and real receipts; `claim_get` still requires tag publication (`TAGGING_NOT_PUBLISHED`) — needs an extraction-review read or documented `not_run` for this slice.

## 5. Unresolved human inputs (need coordinator/user decision — do not invent)

- Budget/price: Upstage price recheck past 2026-09-16; whether to top up / keep shared USD 10 ceiling; keep `.local/upstage/budget.sqlite3` (deleting = unauthorized new allowance).
- Rights/license gate for any real report used in the pilot (which PDF, consent/rights profile IDs, allowed regions `MODEL_ALLOWED_PROCESSING_REGIONS`).
- Runtime/consent/rulepack bindings for the pilot tenant (registry profile IDs, `consent_profile_id`, rulepack version/sha).
- Region/processing approval for sending untrusted document text to Upstage (preflight `allowed_regions`).
- Preliminary-classifier and source-quality (visual/bbox) approval owners — until then, unverified-source block stays and grades stay null.
- Full E/DATA/APPENDIX evaluation + staging gate remain `not_run`; this slice is a local pilot, NOT a production release (Master §6/P0 vs release distinction holds).

## 6. Acceptance mapping

- Exact files/functions: listed in §1–§2 with `path:line` anchors.
- Current synthetic gates: §2 (9 items).
- Minimal changes: §3 (4 steps, extraction-only slice).
- Unresolved human inputs: §5.
- No generic architecture essay; no code/contract/price/model-ARN invented.

Coordinator clarification: authorized local Upstage tests remain within the existing USD 10 ledger; no renewed budget permission is needed. Public-service processing/rights bindings remain unresolved. The new UpstageClaimExtractor now exists but is not wired into application composition.
