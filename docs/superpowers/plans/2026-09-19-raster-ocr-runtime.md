# Independent raster OCR runtime integration plan

> **For agentic workers:** Use superpowers:executing-plans for this plan. Follow existing repository test-first and immutable-publication rules. No user confirmation is required for the already-authorized local implementation and bounded experiments.

**Goal:** A fresh authorized local run can recover a paragraph whose native text/geometry passed but whose rendered OCR disagreed, using an independently read raster receipt. The claim then reaches the existing tagging pipeline; unsupported evidence remains unknown.

**Architecture:** Extend the existing parser worker, fenced job store and read-side replay together. Keep v1-v4 behavior unchanged and introduce v5 only when the separately authorized raster mode is enabled. Reuse the existing provider transport/shared ledger and tested raster composition. No new service, dependency or cloud deployment.

**Current evidence:** 1be6b21 experimental composition, actual Doosan raster receipt at `.local/doosan-independent-raster-ocr`, and immutable evidence JSON under `evidence/`. It recovers one additional source block in memory. It does not yet publish a production/local-worker checkpoint.

## Invariants and ownership

- Domain labels/rules are unchanged; this is source visibility only.
- Original PDF, canonical text, offsets, coordinates, native receipts and prior review revisions are immutable.
- Request/receipt pins come from authenticated tenant-scoped server storage, not an HTTP caller's chosen hashes.
- Existing text extractor/tagger grants do not authorize raster upload. A distinct local-test vision binding, source-scoped consent and image consent are required.
- Actual provider region attestation remains not_run; local approval is never deployment approval.
- The shared cumulative USD20 ledger remains authoritative, including seven unsettled reservations. Unknown requests are never retried or refunded automatically.
- No reader invokes OCR/network. Native + external results must replay from original bytes and pinned artifacts.
- Only readable nonempty `rendered_text_unresolved` native records qualify; native mismatch/clipping/interactive/unavailable/empty cases remain unresolved.

## 1. Separate raster preflight gate

Files: `packages/proofops/application/preflight.py`, new `tests/integration/test_raster_preflight.py`, runtime contract doc.

1. Write failing tests for a distinct vision binding, pinned Document Parse model/endpoint/mode, explicit image consent, exact source/right scope, expiration/revocation, cross-tenant denial and forbidden live probe.
2. Reuse the common local approval/source-scope checks; extend their private implementation with a strictly internal document-parse branch. Do not broaden the public extractor/tagger gates.
3. Pin `document-parse-260128`, `UpstageParseProbe`, `/v1/document-digitization`, standard/enhanced mode and bounded pages. Do not substitute token pricing/context limits for page billing.
4. Run raster/extractor/tagger preflight regressions and architecture checks. Commit the independently testable gate; it makes no model call.

## 2. Freeze configuration and authorize each call

Files: `application/runs.py`, local API composition/config, worker runtime construction, pilot CLI; existing config/preflight tests.

1. Add an optional all-or-none frozen group for raster runtime grant/hash and raster policy/hash. Absent group preserves old snapshots exactly; client-supplied unknown fields remain rejected.
2. Resolve runtime/rights/consent through Registry at creation and again immediately before dispatch; compare current artifacts with frozen pins. Image consent and actual source/right checks are mandatory.
3. Move reusable raster preparation/replay and visibility composition into local adapters, preserving evaluation imports as thin compatibility exports if necessary. Runtime cannot depend on evaluation scripts.
4. Include helper/model/renderer versions in the frozen policy. Separate the immutable consent to call from the returned provider receipt.
5. Add revocation/expiry/different-document tests proving zero calls and zero reservations.

## 3. Atomic v5 publication and replay

Files: `apps/worker/src/proofops_worker/local_runner.py`, `adapters/local/job_store.py`, `adapters/local/run_artifacts.py`; extend native worker integration tests.

1. Define v5 envelope before implementation: existing native-v2 attestation, frozen raster policy hash, immutable request/receipt artifact references and composed output graph hash. Keep original native receipt separate.
2. Add job-store bindings for the exact raster input/receipt artifacts using the existing tenant/run/job keys, immutable writes and active lease fencing. No new SQL table is needed; logical record contract changes are tested.
3. Register/reserve each request before dispatch. A crash after dispatch with no settled receipt remains unresolved; no blind retry. Preserve actual page cost and model-call accounting without inventing token counts.
4. Batch eligible crops within provider limits, bounded by authorized run budget. Never silently drop remaining failures from coverage or turn them into absence. A provider failure cannot publish its source as verified.
5. Publish only after native replay, raster replay, composed graph hash and every artifact/policy pin pass. Reject new raster fields masquerading as legacy v1-v4.
6. Read-side loader fetches trusted pointers, validates same pins, reproduces composition offline and validates output graph hash before exposing source refs. Cache only after full success; any extended cache key must include raster receipts/policy.
7. Test fake-HTTP end-to-end parse→extract→tag: one eligible source recovered, ineligible cases unchanged, duplicate/cancelled worker cannot publish, foreign artifact cannot bind, restart reads call no provider.

## 4. Real evaluation and rollout checks

1. Run Ruff/format, mypy, unit/integration/contract/security/build and staging gate. Run CI on the exact head.
2. Use a fresh Doosan state, same page scope and shared ledger; preserve old states. Verify additional verified source reaches an actual candidate review without weakening element/assurance binding.
3. Run a different report/layout to check the fallback is not specific to the Doosan crop. Report source coverage, literal attribution and semantic gold separately.
4. Inspect original crop and accepted citation; measure cold/repeated reads and added provider calls/cost. Record raw receipt hashes and failures, not just successful examples.
5. Update PR #6 and completion ledger with exact commands, results, cost and remaining coverage limits. Do not claim production readiness or approved domain rules.

## Compatibility / rollback

- v1-v4 inputs and published checkpoints retain their existing schemas/pins; no backfill or rewrite.
- v5 reader, store and writer ship together. Old readers must reject v5 or reserved raster fields rather than treating them as v4.
- Disable raster mode for new runs to roll back calls; retain v5 replay support for existing immutable data. Do not delete reservations or provenance.
- Artifact/hash mismatch remains a read failure. A missing/unavailable OCR artifact never becomes absent evidence.
- No new public HTTP fields are required for the first local composition; do not expand product scope while adding this parser option.

## Review decisions to apply during steps 2–4

- Freeze and compare the run's exact `selected_pages`, not just page count. Every crop's physical page must be in that list at preparation, dispatch, commit and replay. Request source IDs must belong to that run's canonical graph.
- Reserved v5 keys (`raster_ocr_policy_sha256`, `raster_ocr_artifacts`, `raster_ocr_coverage`) must reject legacy v1-v4 envelopes at both commit and read boundaries. Roll out this rejection before enabling v5 writes.
- New raster replay requires provider-reported `document-parse-260128` exactly. Historical generic Document Parse/table adapters may accept aliases; do not broaden new raster authorization to inherit that behavior.
- Frozen policy and request ownership envelope include mode, max pages/calls, eligible/requested source IDs and actual submission page count. Compare mode and actual count against the grant at every dispatch; changing standard/enhanced requires a new request identity.
- Persist receipt ownership as tenant/run/job/document-version/parse-manifest/request-ID plus transport request/response hashes. A receipt with identical PDF bytes from another tenant/job is not interchangeable. Get pins from that scoped server record.
- Resolve and freeze the actual rights artifact from Registry and document-version metadata; the gate's rights string is only a comparison input, not proof of rights by itself.
- Freeze both raster/composition helper code hashes and renderer/writer/image versions before reservation. Include those pins in extended replay-cache keys and final graph identity. Preflight authorization does not replace this execution policy.
- Persist eligible/requested/corroborated/unresolved/failed source sets in coverage; omitted eligible sources remain unresolved. Partial batches and budget exhaustion must not imply absence.
- Application preflight must not import adapter implementations to share constants. Add contract tests against transport pins/page bounds to detect drift while preserving dependency direction.

## Implementation checkpoint — 2026-09-19

Step 1 is implemented. Step 2 has adapter migration and optional complete
run-snapshot policy/grant freezing, including creation-time Registry preflight
and store integrity checks. Existing workers reject this optional group before
job access until v5 is implemented. No paid calls were made in this stage.
Still outstanding in step 2: composition/CLI wiring and immediate pre-dispatch
revalidation. Steps 3 and 4 remain open. This checkpoint does not enable fallback
in a real parser run or count the experimental recovered block as published.

Step 2 now also has scoped request preparation with current Registry/profile,
lease, policy/version, original bytes, selected pages and recomputed native
eligibility checks before/after rendering. It makes no reservation/call. Step 3's
legacy-field rejection is in place at the shared commit/read checkpoint boundary.
Next implementation: fenced persistent ownership/request and receipt records with
max_calls across retries; dispatch through shared ledger; coordinated v5
publication and replay. Do not remove the worker's unsupported guard until that
whole path has a fake-HTTP end-to-end regression and passes replay checks.
