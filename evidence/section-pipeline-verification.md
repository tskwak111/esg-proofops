# Section-scoped extraction and search — 2026-09-09

Continuation of the user-approved E narrative + all ESG DATA + all APPENDIX workflow.
No domain grading rule, production API/DB schema or dependency changed.

## What now runs

1. `evaluation/report_sections.py` policy v4 reads small TOC link labels when
   navigation/large headings cannot supply E or evidence containers. It resolves
   named destinations and explicit internal page references; never printed-page
   arithmetic or external URLs. KB KSSB p5 visually/textually checked: E p17–64,
   Appendix p89–112; other 40 pages remain unknown. Unlabeled p1/p5 navigation
   links are recorded as issues. Last page is included conservatively, not approved
   as readable text. The other four reports retain their earlier E/evidence ranges.
2. `evaluation/section_pipeline.py` checks tenant-authorized graph identity,
   original source hash, current map policy/hash, and recomputes ranges from anchors.
   Tampered page lists are rejected even if the caller recomputes the map hash.
   It feeds E pages into existing `ClaimScope` and `prepare(..., mode="all_text")`.
   No E range means an explicit error, never implicit full-document extraction.
3. `SectionSearch` implements the existing evidence-search port against one graph.
   It searches E plus the entire DATA/APPENDIX set, including S/G/glossary. Each hit
   carries the exact tenant/version/manifest/index generation, source ID and raw-text
   hash. Map hash is included in index generation. Lexical top-20 hits remain
   bounded candidates; vectors return not_run. Unknown/missing pages stay in the
   plan rather than becoming absent evidence. The existing retrieval layer keeps
   unverified sources unresolved and rejects automatic promotion.

CLI, no model calls by default:

```sh
uv run --no-sync python -m evaluation.section_pipeline \
  --pdf PATH_TO_PDF --manifest PATH_TO_MANIFEST \
  --section-map PATH_TO_MAP --output NEW_PLAN_JSON \
  --query '온실가스 Scope 1 2019 2030'
```

Outputs use exclusive creation. Older maps/manifests are preserved. The new bridge
requires current-policy maps; re-inspect an original PDF to create a new map instead
of rewriting an old artifact. Rollback: stop this opt-in local command; no migration
or production full-discovery behavior changed.

## LG Chem full selected-scope parse and model sample

Fresh manifest `1aaf9890-eaef-4898-812c-0718a63036a7` combines E16–49 and DATA/APPENDIX97–119
in **one 57-page graph**, avoiding cross-manifest evidence joins. Original six older
batch manifests are unchanged. OpenDataLoader + existing auxiliary parsing produced
8,004 canonical blocks and 222 issues; `load_verified` successfully replayed the
saved artifacts. Here “verified load” means artifact integrity, **not source_quality
approval**. This is fast_preview, no vision, no accepted source evidence.

E has 4,893 source blocks: 1,892 eligible text blocks → 237 bounded context-preserving
packets. Deferred: 2,897 structures, 92 unlocated blocks and 12 conflicted blocks.
Selected claim/evidence pages have no missing page numbers; this does not establish
that every sentence, chart or table cell was read correctly.

Only packets 159 and 164 (0-based) were sent to Upstage: **2/237, not a full-report
live run**. The first packet crosses p23/p24 and the second is p24. Local sentence-ID
validation accepted both responses and 13 p24 sentence candidates. These include
compound claims and short table-like descriptions; atomicity is not_reviewed.
Requests now record `section_map_sha256` alongside original/wire packet hashes.

All 13 candidates had lexical search hits; seven also had DATA/APPENDIX hits. This
is routing coverage only, not retrieval accuracy or confirmed substantiation.
For example, the 2019 baseline/2030 goal candidate returned p98/112/115 among its
hits; those pages are not automatically evidence for the same year/Scope/value.
Full-quote lexical ranking favors long prose and can retrieve unrelated cells.
Metric, year, unit, entity and boundary binding plus table/header/footnote context
still require the existing source-verification/tagging stages. No grade/label generated.

- Live input/output: 2,813 / 62 tokens.
- Added settled estimate including VAT allowance: **$0.000505065**.
- Ledger before: 61 calls, committed/reserved $2.0314100600.
- Ledger after: 63 calls, committed/reserved **$2.0319151250**, two earlier unsettled
  calls retained. User's cumulative $10 cap remains enforced; no ledger reset.

Artifacts: `.local/section-pipeline/final/` maps and LG plan;
`.local/section-pipeline/live-two-packets/` exact requests, responses, validation,
candidate links and budget receipts. Compact results and hashes are preserved in
`evidence/section-pipeline-results.json`.

## Agent review and checks

Orca Run `run_6bfec16d56c9`, Task `task_cec4af508e21`, Dispatch `ctx_99644a2806fc`.
OpenCode `opencode/muse-spark-1.3-contributor-free` performed read-only TOC review.
Accepted fixes: English climate/carbon and glossary routing, explicit-array internal
destinations, evidence-only TOC adoption, and unlabeled-link issue recording.
Rotated/non-origin TOCs remain an explicit unsupported-geometry issue until affine
link-label resolution is implemented; no guessed rectangle transform was added.
Worker completed, release reported external-terminal retention, and this task's
coordinator-created terminal was explicitly closed; no active workers remain.

- Generated-PDF tests initially failed for small TOC, array destinations and English
  labels, then passed after fixes. External URI actions cannot supply evidence pages.
- Integration exercises real `discover_atomic_claims` and `retrieve_evidence` with
  synthetic source data: scoped claim extraction, all S data inclusion, missing-page
  reporting, map/tenant/index tamper rejection and unverified-hit non-promotion.
- Full suite: **1423 passed**, two existing Starlette/AnyIO warnings, 101.05s.
  `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`.
  Additional external-URI assertion plus targeted rerun: **9 passed**.
- Ruff lint/format passed (226 files); workspace mypy passed (143 sources).
- All four Python package wheels/sdists built; architecture and supply-chain/secret
  gates passed. No dependency or SBOM change required.
- Vision, real atomic decomposition/three-replica tagging, approved bindings, grading,
  production API E2E and AWS remain **not_run** here. This local test does not change
  human domain gaps or claim independent gold accuracy.
