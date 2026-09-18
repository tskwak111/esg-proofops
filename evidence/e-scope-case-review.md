# LG Chem E/appendix case review — 2026-09-09

Kiro reviewed local parser artifacts in Orca task `task_aa099a7642a4`.
The coordinator checked the findings against physical page numbers and corrected
scope/interpretation errors below. This is an agent review, not human approval,
a gold label, a live product-model run or visual source verification.

Source SHA256: `c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde`.
The original PDF and prior six batch manifests remain unchanged.

## Page scope

Observed headings: climate response p16, circular economy p32, environmental
impact p36, natural capital p45; occupational safety starts p50. Environmental
ESG data starts p97 and continues through p102; SOCIAL data starts p103 and
GOVERNANCE data p107. GRI INDEX starts p111, SASB p115, ASSURANCE p117.
The worker's coarse 20-page batch ranges were not accurate section boundaries.
Use **E narrative 16–49 and environmental data 97–102** as a declared development
scope; common methodology and assurance pages require E-relevant claim bindings.
This is a manually inspected scope proposal, not an automatic section detector.
The runnable case covers only p24, p97 and p117.

## Source cases and limits

- p24 states a 2030 Scope 1/2 carbon-neutral-growth target with a 2019 baseline
  of 951만 tCO₂e. The value and target year are directly in the claim. The p29
  table and its p97 environmental-data counterpart show 2023–2025 values,
  including global Scope 1/2 of 8,889,779 for 2025. They do not contain a 2019
  column. This is **not a contradiction or proof of achieving a future target**;
  the organizational boundary and baseline comparison remain unresolved.
  A missing appendix baseline column does not erase direct evidence in the claim.
- p27 states that Scope 3 currently covers domestic sites, with global expansion
  planned. The p30 table (environmental appendix counterpart p98) says domestic
  total. This is a candidate scope connection, not an accepted assurance finding.
  The p117 exclusion of overseas energy and Scope 1/2 assurance cannot establish
  Scope 3 coverage. Scope 3 has a separate assurance statement on p118–119 and
  needs its own period/metric/boundary checks. SASB's p115 Scope 1 ratio likewise
  cannot substantiate a Scope 3 claim.

No grade was assigned by the reviewer. A missing target year does not by itself
resolve every goal branch; the frozen rubric's exceptions and gaps still apply.

## Zero-observation diagnosis

The worker reproduced zero observations for the p21–40 batch: 35 unsupported
layouts plus 492 parser cell-alignment conflicts. The scope-title table header
is `Scope 1·2 배출량 | 단위 | 2023 | 2024 | 2025`, with an unlabelled geography/
intensity column and omitted merged-cell spans in the auxiliary parser output.
The automatic normalizer supports named metric headers and a separate transposed
`Year | Emissions` layout. Its transposed-layout fallback is **not** a safe fix
for this wide-year table: enabling it would treat year columns as metric names.

Coordinator implementation adds explicit source-cell role bindings, with same-table,
row and year-column guards, to reuse the existing decimal/provenance normalization.
It does not infer merged labels, fix malformed units, relax parser conflicts or
approve model semantics. Ordinary automatic normalization remains conservative.

Artifacts: `.local/e-scope-review/normalize_repro.py`, `normalize_repro.log`,
and `.local/corpus-geometry/full-document/`. Executed case and final checks are
recorded in `evidence/e-scope-verification.md`.

Orca reported `agent_prompt_stalled` on launch although the injected task executed.
The worker's completion was accepted as `msg_6c4c649b738e`; its dispatch was released,
and the coordinator-created terminal was closed (`ptyKilled=true`) before acknowledgment.
